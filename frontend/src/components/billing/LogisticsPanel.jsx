import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Truck, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { api, errMsg } from "@/lib/api";
import { fmtDate, fmtEur2 } from "@/lib/constants";
import { ClientPreview, ExpensesTab, LaborTab, TripTeam, slimExpense, slimLabor } from "@/components/billing/LogisticsTabs";

const sel = "h-9 rounded-lg border border-border bg-background px-2 text-xs";
const TYPE = { delivery: "Trajet — Livraison / installation", pickup: "Trajet — Retrait / démontage", extra: "Trajet supplémentaire" };
const MODES = { "": "Mode par défaut", zone: "Forfait par zone", computed: "Calcul (mise à disposition + km)", manual: "Manuel" };
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
const KEYS = ["id", "type", "active", "title", "date", "slot_start", "slot_end", "origin_id", "vehicles", "distance_manual", "distance_km_rt", "tolls_ht", "pricing_mode", "price_ht"];
const slim = (t) => ({ ...Object.fromEntries(KEYS.map((k) => [k, t[k]])), distance_km_rt: Number(t.distance_km_rt) || 0, tolls_ht: Number(t.tolls_ht) || 0, price_ht: Number(t.price_ht) || 0,
  vehicles: t.vehicles?.map((v) => ({ vehicle_id: v.vehicle_id || "", rental_label: v.rental_label || "", rental_cost_ht: Number(v.rental_cost_ht) || 0, rental_volume_m3: Number(v.rental_volume_m3) || 0, rental_capacity_kg: Number(v.rental_capacity_kg) || 0 })) ?? null });

export const linesOf = (blocks) => blocks.filter((b) => b.type === "line" && b.equipment_id && Number(b.qty) > 0).map((b) => ({ equipment_id: b.equipment_id, qty: Number(b.qty) }));

export function LogisticsPanel({ quoteId, blocks, dates, onClose, onApply }) {
  const [d, setD] = useState(null);
  const [tab, setTab] = useState("transport");
  const timer = useRef(null);
  const ctx = useRef({ blocks, dates });
  ctx.current = { blocks, dates };
  const call = useCallback((patch, save) => api[save ? "put" : "post"](`/quotes/${quoteId}/trips${save ? "" : "/compute"}`, { lines: linesOf(ctx.current.blocks), dates: ctx.current.dates, ...patch }), [quoteId]);
  useEffect(() => { call({}).then((r) => setD(r.data)).catch((e) => toast.error(errMsg(e))); }, [call]);
  if (!d) return null;
  const body = (x) => ({ trips: x.trips.map(slim), display: x.display, show_weight: x.show_weight, labor: x.labor.map(slimLabor), expenses: x.expenses.map(slimExpense), labor_display: x.labor_display });
  const push = (next, now) => { setD(next); clearTimeout(timer.current); timer.current = setTimeout(() => call(body(next)).then((r) => setD(r.data)).catch((e) => toast.error(errMsg(e))), now ? 0 : 500); };
  const up = (id, patch, now) => push({ ...d, trips: d.trips.map((t) => (t.id === id ? { ...t, ...patch } : t)) }, now);
  const save = () => { clearTimeout(timer.current); call(body(d), true).then((r) => { toast.success("Logistique enregistrée : lignes mises à jour dans le devis, pensez à enregistrer le devis"); onApply(r.data); }).catch((e) => toast.error(errMsg(e))); };
  const pill = (on) => `h-8 rounded-full border px-3 text-xs font-medium ${on ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`;
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-2xl" data-testid="logistics-panel">
        <SheetHeader><SheetTitle>Logistique & équipe</SheetTitle><SheetDescription>Les trajets génèrent les lignes de la section « {d.section} ». Distance et coût ne sont jamais montrés au client.</SheetDescription></SheetHeader>
        <div className="mt-4 flex gap-2">{[["transport", "Transport"], ["team", "Équipe"], ["expenses", "Frais de mission"], ["preview", "Aperçu client"]].map(([k, l]) => <button key={k} type="button" className={pill(tab === k)} onClick={() => setTab(k)} data-testid={`logistics-tab-${k}`}>{l}</button>)}</div>
        {tab === "team" && <LaborTab d={d} push={push} pill={pill} />}
        {tab === "expenses" && <ExpensesTab d={d} push={push} />}
        {tab === "preview" && <ClientPreview d={d} blocks={blocks} />}
        {tab !== "transport" ? <div className="mt-4 flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Fermer</Button><Button type="button" onClick={save} data-testid="logistics-save">Enregistrer et mettre à jour le devis</Button></div> : <div className="mt-4 space-y-4">
          {d.all_on_site && <p className="rounded-xl bg-emerald-500/10 p-3 text-sm" data-testid="trips-all-on-site">Tout le matériel est déjà sur place : la livraison est remplacée par une « Mise en place sur site » (main-d'œuvre seule, sans véhicule). Saisissez son prix.</p>}
          {!d.has_venue && <p className="rounded-xl bg-amber-500/10 p-3 text-sm text-amber-700">Devis sans lieu d'événement : saisissez la distance à la main.</p>}
          {d.trips.map((t, i) => (
            <div key={t.id} className={`rounded-2xl border border-border p-4 ${t.enabled ? "" : "opacity-60"}`} data-testid={`trip-${t.type}-${i}`}>
              <div className="flex flex-wrap items-center gap-2"><Truck className="h-4 w-4" /><b className="text-sm">{t.on_site ? "Mise en place sur site" : TYPE[t.type]}</b>
                <span className="text-xs text-muted-foreground">{t.date ? `${fmtDate(t.date)}${t.slot_start || t.slot_end ? ` · ${[t.slot_start, t.slot_end].filter(Boolean).join(" – ")}` : ""}` : "date à préciser"}</span><span className="flex-1" />
                <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={t.active} onChange={(e) => up(t.id, { active: e.target.checked }, true)} data-testid={`trip-active-${i}`} />Actif</label>
                {t.type === "extra" && <button type="button" aria-label="Supprimer le trajet" onClick={() => push({ ...d, trips: d.trips.filter((x) => x.id !== t.id) }, true)} data-testid={`trip-remove-${i}`}><Trash2 className="h-4 w-4" /></button>}</div>
              {!t.enabled && t.active && <p className="mt-1 text-xs text-muted-foreground">Période désactivée dans le bloc Dates du devis.</p>}
              {t.type === "extra" && <div className="mt-2 flex flex-wrap gap-2"><Input className="h-9 w-48" placeholder="Intitulé" value={t.title} onChange={(e) => up(t.id, { title: e.target.value })} /><Input className="h-9 w-40" type="date" value={t.date} onChange={(e) => up(t.id, { date: e.target.value })} data-testid={`trip-date-${i}`} /><Input className="h-9 w-28" type="time" value={t.slot_start} onChange={(e) => up(t.id, { slot_start: e.target.value })} /><Input className="h-9 w-28" type="time" value={t.slot_end} onChange={(e) => up(t.id, { slot_end: e.target.value })} /></div>}
              {!t.on_site && <>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs"><select className={sel} value={t.origin_id} onChange={(e) => up(t.id, { origin_id: e.target.value }, true)} aria-label="Entrepôt" data-testid={`trip-origin-${i}`}><option value="">{t.origin_name} (par défaut)</option>{d.warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select>
                  <span>{t.type === "pickup" ? "←" : "→"} {t.destination_name || "lieu à préciser"}</span></div>
                <div className="mt-3 space-y-1.5" data-testid={`trip-vehicles-${i}`}>{(t.vehicles || []).map((v, j) => (
                  <div key={j} className="flex flex-wrap items-center gap-2">
                    <select className={sel} value={v.vehicle_id || "rental"} onChange={(e) => up(t.id, { vehicles: (t.vehicles || []).map((x, k) => (k === j ? (e.target.value === "rental" ? { vehicle_id: "", rental_label: "Camion loué 20 m³", rental_cost_ht: 0, rental_volume_m3: 20, rental_capacity_kg: 1000 } : { vehicle_id: e.target.value }) : x)) }, true)} data-testid={`trip-vehicle-${i}-${j}`}>
                      {d.vehicles.map((x) => <option key={x.id} value={x.id}>{x.name} ({x.capacity_kg} kg{x.volume_m3 ? `, ${x.volume_m3} m³` : ""})</option>)}<option value="rental">Véhicule loué ponctuel…</option></select>
                    {!v.vehicle_id && <><Input className="h-9 w-40" value={v.rental_label} onChange={(e) => up(t.id, { vehicles: (t.vehicles || []).map((x, k) => (k === j ? { ...x, rental_label: e.target.value } : x)) })} placeholder="Désignation" />
                      {[["rental_cost_ht", "Coût HT"], ["rental_volume_m3", "m³"], ["rental_capacity_kg", "kg utiles"]].map(([k2, l]) => <label key={k2} className="flex items-center gap-1 text-xs text-muted-foreground">{l}<Input className="h-9 w-20" type="number" min="0" step="any" value={v[k2]} onChange={(e) => up(t.id, { vehicles: (t.vehicles || []).map((x, k) => (k === j ? { ...x, [k2]: e.target.value } : x)) })} data-testid={`trip-${k2}-${i}-${j}`} /></label>)}</>}
                    <button type="button" aria-label="Retirer le véhicule" onClick={() => up(t.id, { vehicles: (t.vehicles || []).filter((_, k) => k !== j) }, true)} data-testid={`trip-vehicle-remove-${i}-${j}`}><Trash2 className="h-3.5 w-3.5" /></button></div>))}
                  <button type="button" className="text-xs underline" onClick={() => up(t.id, { vehicles: [...(t.vehicles || []), d.vehicles[0] ? { vehicle_id: (d.vehicles.find((x) => !(t.vehicles || []).some((v) => v.vehicle_id === x.id)) || d.vehicles[0]).id } : { vehicle_id: "", rental_label: "Camion loué 20 m³", rental_cost_ht: 0, rental_volume_m3: 20, rental_capacity_kg: 1000 }] }, true)} data-testid={`trip-add-vehicle-${i}`}>+ Ajouter un véhicule</button></div>
                <div className="mt-3 text-xs" data-testid={`trip-load-${i}`}><div className="flex justify-between"><span>Chargé (part « À livrer ») : <b data-testid={`trip-weight-${i}`}>{t.weight_kg} kg</b>{t.volume_m3 ? ` · ${t.volume_m3} m³` : ""} · {t.items} produit(s)</span><span data-testid={`trip-fill-${i}`}>{t.fill_pct} %</span></div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-secondary"><div className={t.fill_pct > 100 ? "h-full bg-red-500" : t.fill_pct > 85 ? "h-full bg-amber-500" : "h-full bg-emerald-500"} style={{ width: `${Math.min(100, t.fill_pct)}%` }} /></div></div>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <label className="flex items-center gap-1">Km aller-retour<Input className="h-9 w-24" type="number" min="0" step="any" value={t.distance_km_rt} onChange={(e) => up(t.id, { distance_km_rt: e.target.value, distance_manual: true })} data-testid={`trip-km-${i}`} /></label>
                  {t.distance_manual && <button type="button" className="underline" onClick={() => up(t.id, { distance_manual: false }, true)} data-testid={`trip-km-auto-${i}`}>recalculer</button>}
                  <span className="text-muted-foreground">{t.distance_source}{t.drive_minutes ? ` · ${Math.floor(t.drive_minutes / 60)} h ${String(t.drive_minutes % 60).padStart(2, "0")} l'aller` : ""}</span>
                  <label className="flex items-center gap-1">Péages HT<Input className="h-9 w-20" type="number" min="0" step="any" value={t.tolls_ht} onChange={(e) => up(t.id, { tolls_ht: e.target.value })} data-testid={`trip-tolls-${i}`} /></label></div></>}
              {!t.on_site && <TripTeam d={d} t={t} i={i} push={push} />}
              {t.alerts.map((a) => <p key={a} className="mt-2 flex items-center gap-1.5 text-xs font-semibold text-red-600" data-testid={`trip-alert-${i}`}><TriangleAlert className="h-3.5 w-3.5" />{a}</p>)}
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-secondary/50 p-2 text-xs">
                {!t.on_site && <select className={sel} value={t.pricing_mode} onChange={(e) => up(t.id, { pricing_mode: e.target.value }, true)} data-testid={`trip-mode-${i}`}>{Object.entries(MODES).map(([k, l]) => <option key={k} value={k}>{k ? l : `${l} : ${MODES[d.default_mode]}`}</option>)}</select>}
                {t.on_site || (t.pricing_mode || d.default_mode) === "manual" ? <label className="flex items-center gap-1">Prix HT<Input className="h-9 w-24" type="number" min="0" step="any" value={t.price_ht} onChange={(e) => up(t.id, { price_ht: e.target.value })} data-testid={`trip-price-input-${i}`} /></label> : <span className="text-muted-foreground">{t.pricing_note}</span>}
                <span className="flex-1" /><span>Prix client <b data-testid={`trip-price-${i}`}>{fmtEur2(t.price_ht)}</b></span>
                {d.can_cost && <span data-testid={`trip-cost-${i}`}>· coût {fmtEur2(t.cost_ht)} · marge {fmtEur2(t.margin_ht)}</span>}</div>
            </div>))}
          <button type="button" className="text-sm underline" onClick={() => push({ ...d, trips: [...d.trips, { id: uid(), type: "extra", active: true, title: "", date: "", slot_start: "", slot_end: "", origin_id: "", vehicles: null, distance_manual: false, distance_km_rt: 0, tolls_ht: 0, pricing_mode: "", price_ht: 0, alerts: [], enabled: true }] }, true)} data-testid="trip-add"><Plus className="mr-1 inline h-4 w-4" />Trajet</button>
          <div className="rounded-2xl border border-border p-4 text-sm" data-testid="trips-display"><div className="mb-2 font-semibold">Affichage client</div>
            <div className="flex flex-wrap items-center gap-2">{[["detailed", "Détaillé : une ligne par trajet"], ["grouped", "Regroupé : « Transport aller-retour »"]].map(([k, l]) => <button key={k} type="button" className={pill(d.display === k)} onClick={() => push({ ...d, display: k }, true)} data-testid={`trips-display-${k}`}>{l}</button>)}
              <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={d.show_weight} onChange={(e) => push({ ...d, show_weight: e.target.checked }, true)} data-testid="trips-show-weight" />Afficher le poids transporté</label></div>
            <div className="mt-3 space-y-1 text-xs text-muted-foreground" data-testid="trips-preview">{d.lines.map((l) => <div key={l.source_id} className="flex justify-between gap-3"><span>{l.label}</span><span>{fmtEur2(l.unit_price)}</span></div>)}{!d.lines.length && "Aucune ligne générée."}</div></div>
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Fermer</Button><Button type="button" onClick={save} data-testid="trips-save">Enregistrer et mettre à jour le devis</Button></div>
        </div>}
      </SheetContent>
    </Sheet>);
}
