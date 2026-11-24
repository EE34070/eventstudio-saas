import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Send, Navigation } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Loading, Field, EmptyState } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { dayKey, fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { MissionBoard } from "@/components/logistics/EventLogistics";
import { ShortagesGlobal } from "@/components/logistics/Shortages";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-10 rounded-lg border border-border bg-background px-3 text-sm";

function Day({ write }) {
  const [day, setDay] = useState(dayKey(new Date()));
  const [d, setD] = useState(null);
  const [refs, setRefs] = useState({ vehicles: [], team: [] });
  const [rot, setRot] = useState([]);
  const load = useCallback(() => { api.get("/logistics/day", { params: { day } }).then((r) => setD(r.data)).catch(ko); api.get("/logistics/rotations").then((r) => setRot(r.data)).catch(() => {}); }, [day]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { Promise.all([api.get("/vehicles"), api.get("/team")]).then(([v, t]) => setRefs({ vehicles: v.data.filter((x) => x.active), team: t.data.map((m) => ({ id: m.id, name: m.name, licences: m.licences || [] })) })).catch(() => {}); }, []);
  if (!d) return <Loading />;
  return (
    <div data-testid="logistics-day">
      <Input type="date" className="mb-4 w-48" value={day} onChange={(e) => setDay(e.target.value)} data-testid="logistics-day-input" />
      {d.fleet_alerts.map((a, i) => <p key={i} className="mb-2 rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="fleet-alert">{a.vehicle} : {a.label} {a.late ? "dépassé depuis le" : "le"} {fmtDate(a.date)}</p>)}
      {rot.map((r, i) => <div key={i} className="mb-2 flex flex-wrap items-center gap-3 rounded-xl border border-border p-3 text-sm" data-testid="rotation-proposal"><span className="flex-1">Rotation possible : {r.text}.</span>{write && <Button size="sm" onClick={() => api.post("/logistics/rotations", r).then(() => { toast.success("Transfert créé"); load(); }).catch(ko)} data-testid="rotation-accept">Accepter</Button>}</div>)}
      {d.tours.length > 0 && <div className="card-soft mb-4 p-4" data-testid="logistics-tours"><div className="mb-2 text-sm font-semibold">Tournées du jour</div>{d.tours.map((t) => <div key={t.vehicle} className="text-sm"><b>{t.vehicle}</b> : {t.stops.map((s) => `${s.window_start || "?"} ${s.venue_name || s.event_title} (${s.type_label})`).join(" → ")}</div>)}<p className="mt-2 text-xs text-muted-foreground">{d.tour_note}</p></div>}
      {!d.missions.length ? <EmptyState title="Aucune mission ce jour-là" text="Les missions sont générées depuis l'onglet Matériel d'un événement, ou automatiquement à J-10." /> : <div className="space-y-4">{d.missions.map((m) => (
        <div key={m.id}><div className="mb-1 flex flex-wrap items-center gap-3 text-sm"><Link className="font-semibold underline" to={`/evenements/${m.event_id}`}>{m.event_title}</Link>
          {m.venue.address && <a className="flex items-center gap-1 text-primary" target="_blank" rel="noreferrer" href={`https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${m.venue.address} ${m.venue.zip} ${m.venue.city}`)}`}><Navigation className="h-3.5 w-3.5" />Itinéraire</a>}
          {m.contacts.map((c) => <a key={c.name} href={`tel:${c.phone}`} className="text-xs text-muted-foreground">{c.name}{c.role ? ` (${c.role})` : ""} {c.phone}</a>)}</div>
          <MissionBoard m={m} vehicles={refs.vehicles} team={refs.team} write={write} onChange={load} /></div>))}</div>}
    </div>
  );
}

function Capacities({ write }) {
  const [d, setD] = useState(null);
  const [q, setQ] = useState("");
  const load = useCallback(() => api.get("/logistics/capacities").then((r) => setD(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return <Loading />;
  const val = (v, key) => d.cells.find((c) => c.vehicle_id === v && c.key === key)?.max_qty || "";
  const save = (vehicle_id, key, value, proposal_id = "") => api.put("/logistics/capacities", { vehicle_id, key, max_qty: Number(value) || null, proposal_id }).then(load).catch(ko);
  const rows = [...d.families.map((f) => ({ key: `fam:${f}`, label: `Famille : ${f}` })), ...d.products.map((p) => ({ key: p.id, label: `${p.ref} ${p.name}`, ref: p.ref }))].filter((r) => !q || r.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <div data-testid="capacity-matrix">
      {d.proposals.map((p) => <div key={p.id} className="mb-2 flex flex-wrap items-center gap-3 rounded-xl border border-border p-3 text-sm" data-testid="capacity-proposal"><span className="flex-1">D'après un chargement ({p.computed_pct} % calculé) : {p.vehicle_name} pourrait contenir <b>{p.proposed}</b> × {p.product} (actuel : {p.current}).</span>{write && <Button size="sm" onClick={() => save(p.vehicle_id, p.key, p.proposed, p.id)} data-testid="capacity-proposal-apply">Appliquer</Button>}</div>)}
      <Input className="mb-3 w-64" placeholder="Rechercher un produit ou une famille…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="capacity-search" />
      <p className="mb-2 text-xs text-muted-foreground">Nombre maximal d'unités si le véhicule ne transporte que ce produit. Case vide = capacité inconnue. La valeur d'un produit prime sur celle de sa famille.</p>
      <div className="card-soft overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-border"><th className="px-3 py-2 text-left text-xs">Produit</th>{d.vehicles.map((v) => <th key={v.id} className="px-3 py-2 text-left text-xs">{v.name}</th>)}</tr></thead>
        <tbody>{rows.map((r) => <tr key={r.key} className="border-b border-border last:border-0"><td className="px-3 py-1.5">{r.label}</td>{d.vehicles.map((v) => <td key={v.id} className="px-3 py-1.5"><input type="number" min="0" disabled={!write} defaultValue={val(v.id, r.key)} key={`${v.id}${r.key}${val(v.id, r.key)}`} onBlur={(e) => String(val(v.id, r.key)) !== e.target.value && save(v.id, r.key, e.target.value)} className="h-8 w-24 rounded border border-border bg-background px-2" aria-label={`${r.label} — ${v.name}`} data-testid={`cap-${v.name}-${r.ref || r.key}`} /></td>)}</tr>)}</tbody></table></div>
    </div>
  );
}

const LG = { delivery_address: "", access_hours: "", delivery_start: "", delivery_end: "", pickup_start: "", pickup_end: "", max_length_m: 0, max_height_m: 0, max_tonnage_t: 0, tailgate_required: false, dock_distance_m: 0, stairs: "", parking: "", gate_code: "", instructions: "", preferred_channel: "email", reminders_off: false };
function VenueSheets({ write }) {
  const [venues, setVenues] = useState([]);
  const [id, setId] = useState("");
  const [f, setF] = useState(LG);
  useEffect(() => { api.get("/venues").then((r) => setVenues(r.data)).catch(ko); }, []);
  useEffect(() => { setF({ ...LG, ...(venues.find((v) => v.id === id)?.logistics || {}) }); }, [id, venues]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const num = ["max_length_m", "max_height_m", "max_tonnage_t", "dock_distance_m"];
  const save = () => api.put(`/venues/${id}/logistics`, { ...f, ...Object.fromEntries(num.map((k) => [k, Number(f[k]) || 0])) }).then((r) => { toast.success("Fiche logistique enregistrée"); setVenues(venues.map((v) => (v.id === id ? { ...v, logistics: r.data } : v))); }).catch(ko);
  const txt = [["delivery_address", "Adresse de livraison (si différente)"], ["access_hours", "Horaires d'accès"], ["stairs", "Escaliers / monte-charge"], ["parking", "Stationnement"], ["gate_code", "Code portail"]];
  return (
    <div data-testid="venue-logistics">
      <select className={`${sel} mb-4 w-80`} value={id} onChange={(e) => setId(e.target.value)} data-testid="venue-logistics-select"><option value="">Choisir un lieu…</option>{venues.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select>
      {id && <div className="card-soft grid grid-cols-2 gap-4 p-5 md:grid-cols-4">
        {[["delivery_start", "Livraison de"], ["delivery_end", "à"], ["pickup_start", "Retrait de"], ["pickup_end", "à"]].map(([k, l]) => <Field key={k} label={l}><Input type="time" value={f[k]} onChange={set(k)} data-testid={`vl-${k}`} /></Field>)}
        {[["max_length_m", "Longueur max (m)"], ["max_height_m", "Hauteur max (m)"], ["max_tonnage_t", "Tonnage max (t)"], ["dock_distance_m", "Distance quai → salle (m)"]].map(([k, l]) => <Field key={k} label={l}><Input type="number" min="0" step="0.1" value={f[k]} onChange={set(k)} data-testid={`vl-${k}`} /></Field>)}
        {txt.map(([k, l]) => <Field key={k} label={l} className="col-span-2"><Input value={f[k]} onChange={set(k)} /></Field>)}
        <Field label="Canal préféré"><select className={sel} value={f.preferred_channel} onChange={set("preferred_channel")}><option value="email">E-mail</option><option value="whatsapp">WhatsApp</option><option value="both">Les deux</option></select></Field>
        <Field label="Consignes" className="col-span-2 md:col-span-4"><Textarea rows={2} value={f.instructions} onChange={set("instructions")} /></Field>
        <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={f.tailgate_required} onChange={set("tailgate_required")} data-testid="vl-tailgate" />Hayon nécessaire</label>
        <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={f.reminders_off} onChange={set("reminders_off")} data-testid="vl-reminders-off" />Couper les relances pour ce lieu</label>
        <p className="col-span-2 text-xs text-muted-foreground md:col-span-4">Les contacts du lieu (rôle, langue) se gèrent dans la fiche du lieu ; le dépôt lié dans Entrepôts & stocks.</p>
        {write && <Button className="col-span-2 md:col-span-1" onClick={save} data-testid="venue-logistics-save">Enregistrer</Button>}
      </div>}
    </div>
  );
}

function Reminders({ write, admin }) {
  const [d, setD] = useState(null);
  const [edit, setEdit] = useState({});
  const load = useCallback(() => api.get("/logistics/reminders").then((r) => setD(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return <Loading />;
  const rule = (k, patch) => api.put("/logistics/reminders/rules", { rules: d.rules.map((r) => ({ key: r.key, channel: r.channel, mode: r.mode, active: r.active, days: r.days, ...(r.key === k ? patch : {}) })) }).then(load).catch(ko);
  const ST = { draft: "Brouillon", sent: "Envoyée", failed: "Échec", cancelled: "Annulée" };
  return (
    <div data-testid="logistics-reminders">
      <p className="mb-3 text-sm text-muted-foreground">WhatsApp n'est pas configuré : tout part par e-mail de repli, journalisé. En mode « brouillon », rien n'est envoyé sans votre validation. Aucun envoi pour un événement non confirmé.</p>
      <div className="card-soft mb-5 divide-y divide-border">{d.rules.map((r) => <div key={r.key} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm" data-testid={`rule-${r.key}`}><span className="min-w-0 flex-1 font-semibold">{r.label}</span>
        <select className={sel} disabled={!admin} value={r.channel} onChange={(e) => rule(r.key, { channel: e.target.value })}><option value="email">E-mail</option><option value="whatsapp">WhatsApp</option><option value="both">Les deux</option></select>
        <select className={sel} disabled={!admin} value={r.mode} onChange={(e) => rule(r.key, { mode: e.target.value })} data-testid={`rule-mode-${r.key}`}><option value="draft">Brouillon (validation)</option><option value="auto">Automatique</option></select>
        <label className="flex items-center gap-2"><input type="checkbox" disabled={!admin} checked={r.active} onChange={(e) => rule(r.key, { active: e.target.checked })} />Active</label></div>)}</div>
      {write && <Button size="sm" variant="outline" className="mb-4" onClick={() => api.post("/logistics/reminders/run").then((r) => { toast.success(`${r.data.created} relance(s) préparée(s)`); load(); }).catch(ko)} data-testid="reminders-run">Préparer les relances dues</Button>}
      {!d.logs.length ? <EmptyState title="Aucune relance" /> : <div className="space-y-3">{d.logs.map((l) => { const e = edit[l.id] || l; return (
        <div key={l.id} className="card-soft p-4 text-sm" data-testid={`reminder-${l.status}`}><div className="flex flex-wrap items-center gap-2"><b>{l.rule_label}</b><span className="text-muted-foreground">→ {l.to_name} ({l.to}) · {l.language}</span><span className="ml-auto rounded-full bg-secondary px-2.5 py-0.5 text-[11px] font-semibold">{ST[l.status]}</span></div>
          {l.fallback && <p className="text-xs text-muted-foreground">{l.fallback}</p>}{l.error && <p className="text-xs font-semibold text-red-600">{l.error}</p>}
          {["draft", "failed"].includes(l.status) && write ? <><Input className="mt-2" value={e.subject} onChange={(x) => setEdit({ ...edit, [l.id]: { ...e, subject: x.target.value } })} /><Textarea className="mt-2" rows={4} value={e.body} onChange={(x) => setEdit({ ...edit, [l.id]: { ...e, body: x.target.value } })} />
            <div className="mt-2 flex gap-2"><Button size="sm" onClick={() => api.post(`/logistics/reminders/${l.id}/send`, { subject: e.subject, body: e.body }).then(() => { toast.success("Relance envoyée"); load(); }).catch((x) => { ko(x); load(); })} data-testid="reminder-send"><Send />Valider et envoyer</Button><Button size="sm" variant="ghost" onClick={() => api.delete(`/logistics/reminders/${l.id}`).then(load).catch(ko)}>Annuler</Button></div></>
            : <p className="mt-1 whitespace-pre-line text-muted-foreground">{l.subject}</p>}</div>); })}</div>}
    </div>
  );
}

export default function Logistique() {
  const { can } = useMe();
  const [sp, setSp] = useSearchParams();
  const vue = sp.get("vue") || "jour";
  const write = can("events:write");
  const tabs = [["jour", "Missions du jour"], ["manques", "Événements avec manques"], ["capacites", "Capacités de chargement"], ["lieux", "Fiches lieux"], ["relances", "Relances lieux"]];
  return (
    <div data-testid="logistics-page">
      <PageHeader title="Logistique" subtitle="Missions de livraison et de retrait, répartition dans les véhicules, capacités déclarées et relances aux lieux." />
      <div className="mb-5 inline-flex flex-wrap rounded-2xl border border-border bg-card p-1">{tabs.map(([k, l]) => <button key={k} onClick={() => setSp(k === "jour" ? {} : { vue: k })} data-testid={`logistics-tab-${k}`} className={`rounded-full px-4 py-1.5 text-xs font-semibold ${vue === k ? "bg-foreground text-background" : "text-muted-foreground"}`}>{l}</button>)}</div>
      {vue === "manques" ? <ShortagesGlobal /> : vue === "capacites" ? <Capacities write={can("catalog:write")} /> : vue === "lieux" ? <VenueSheets write={can("venues:write")} /> : vue === "relances" ? <Reminders write={write} admin={can("org:write")} /> : <Day write={write} />}
    </div>
  );
}
