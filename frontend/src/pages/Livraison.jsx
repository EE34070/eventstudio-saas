import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Truck, ChevronLeft, ChevronRight, MapPin, Clock, Phone, Navigation, Camera, PenLine, FileText, ArrowUp, ArrowDown, PackageCheck, Eraser } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { PageHeader, Loading, EmptyState, Meta, Field } from "@/components/common";
import { FileImg, openFile } from "@/lib/files";
import { api, errMsg } from "@/lib/api";
import { dayKey, fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

const shiftDay = (d, n) => { const x = new Date(d + "T00:00"); x.setDate(x.getDate() + n); return dayKey(x); };

function SignPad({ onChange }) {
  const ref = useRef(null);
  const on = useRef(false);
  const pos = (e) => { const c = ref.current; const r = c.getBoundingClientRect(); return [((e.clientX - r.left) * c.width) / r.width, ((e.clientY - r.top) * c.height) / r.height]; };
  const down = (e) => { on.current = true; const g = ref.current.getContext("2d"); g.lineWidth = 3; g.lineCap = "round"; g.strokeStyle = "#111"; g.beginPath(); g.moveTo(...pos(e)); };
  const move = (e) => { if (!on.current) return; const g = ref.current.getContext("2d"); g.lineTo(...pos(e)); g.stroke(); };
  const up = () => { if (!on.current) return; on.current = false; onChange(ref.current.toDataURL("image/png")); };
  const clear = () => { const c = ref.current; c.getContext("2d").clearRect(0, 0, c.width, c.height); onChange(""); };
  return (
    <div>
      <canvas ref={ref} width={600} height={220} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={up}
        className="w-full touch-none rounded-2xl border border-border bg-white" data-testid="delivery-sign-pad" />
      <Button type="button" size="sm" variant="ghost" className="mt-1" onClick={clear} data-testid="delivery-sign-clear"><Eraser />Effacer</Button>
    </div>
  );
}

function SignDialog({ d, onOpenChange, onDone, url }) {
  const [f, setF] = useState({ signer_name: d.client_name || "", notes: "", signature: "" });
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try { await api.post(url || `/deliveries/${d.id}/sign`, f); toast.success("Bon de livraison signé"); onDone(); onOpenChange(false); } catch (err) { toast.error(errMsg(err)); }
    setBusy(false);
  };
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-lg overflow-y-auto">
        <DialogHeader><DialogTitle className="text-xl font-bold">Signature du client · {d.event_code}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="space-y-4" data-testid="delivery-sign-form">
          <div className="text-sm text-muted-foreground">{d.lines.reduce((n, l) => n + l.qty, 0)} élément(s) livré(s) à {d.venue?.name}.</div>
          <Field label="Nom du signataire"><Input required minLength={2} value={f.signer_name} onChange={(e) => setF({ ...f, signer_name: e.target.value })} data-testid="delivery-signer-input" /></Field>
          <Field label="Réserves / observations"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} data-testid="delivery-notes-input" /></Field>
          <Field label="Signature"><SignPad onChange={(signature) => setF((x) => ({ ...x, signature }))} /></Field>
          <DialogFooter><Button disabled={busy || !f.signature} data-testid="delivery-sign-submit"><PenLine />{busy ? "Enregistrement…" : "Valider la livraison"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Card({ d, idx, count, vehicles, reload, move, write }) {
  const [sign, setSign] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef(null);
  const done = d.status === "livre";
  const v = d.venue || {};
  const dest = v.lat && v.lng ? `${v.lat},${v.lng}` : encodeURIComponent([v.name, v.address, v.zip, v.city].filter(Boolean).join(" "));
  const vehicle = vehicles.find((x) => x.id === d.vehicle_id);
  const upload = async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    setBusy(true);
    for (const file of files) {
      const fd = new FormData();
      fd.append("file", file);
      try { await api.post(`/deliveries/${d.id}/photos`, fd); } catch (err) { toast.error(errMsg(err)); }
    }
    setBusy(false);
    reload();
  };
  return (
    <div className="card-soft p-6" data-testid={`delivery-card-${d.event_code}`}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border text-sm font-bold">{idx + 1}</span>
        <div className="min-w-0 flex-1">
          <Link to={`/evenements/${d.event_id}`} className="block truncate text-lg font-semibold hover:underline">{d.event_title}</Link>
          <div className="truncate text-sm text-muted-foreground">{[v.name, v.address, [v.zip, v.city].filter(Boolean).join(" ")].filter(Boolean).join(", ") || "Lieu à définir"}</div>
        </div>
        {done && <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400" data-testid={`delivery-done-${d.event_code}`}><PackageCheck className="h-4 w-4" />Livré</span>}
        {write && !done && count > 1 && <div className="flex"><Button size="icon" variant="ghost" disabled={idx === 0} onClick={() => move(idx, -1)} aria-label="Monter" data-testid={`delivery-up-${d.event_code}`}><ArrowUp /></Button><Button size="icon" variant="ghost" disabled={idx === count - 1} onClick={() => move(idx, 1)} aria-label="Descendre" data-testid={`delivery-down-${d.event_code}`}><ArrowDown /></Button></div>}
      </div>
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1">
        <Meta icon={Clock}>Départ {d.departure.slice(11, 16)}</Meta>
        <Meta icon={Truck}>{vehicle?.name || "Sans véhicule"}</Meta>
        <Meta icon={MapPin}>{v.city || "—"}</Meta>
        {d.client_phone && <a href={`tel:${d.client_phone}`}><Meta icon={Phone}>{d.client_name} · {d.client_phone}</Meta></a>}
      </div>
      <div className="mt-3 divide-y divide-border text-sm">
        {d.lines.map((l, i) => <div key={i} className="flex gap-3 py-2"><b className="w-10 shrink-0">{l.qty} ×</b><span className="min-w-0 flex-1 truncate">{l.name}</span><span className="text-[13px] text-[#737373]">{l.section || l.ref}</span></div>)}
        {!d.lines.length && <div className="py-2 text-muted-foreground">Aucun matériel sur cet événement.</div>}
      </div>
      {d.photos.length > 0 && <div className="mt-3 flex flex-wrap gap-2" data-testid={`delivery-photos-${d.event_code}`}>{d.photos.map((p) => <button key={p} onClick={() => openFile(p)}><FileImg src={p} className="h-20 w-20 rounded-xl object-cover" /></button>)}</div>}
      {done && <div className="mt-3 text-sm text-muted-foreground" data-testid={`delivery-signed-${d.event_code}`}>Signé par <b className="text-foreground">{d.signer_name}</b> le {fmtDate(d.signed_at.slice(0, 10))} à {d.signed_at.slice(11, 16)}{d.notes ? ` — réserves : ${d.notes}` : ""}</div>}
      <div className="mt-4 flex flex-wrap gap-2">
        <a href={`https://www.google.com/maps/dir/?api=1&destination=${dest}`} target="_blank" rel="noreferrer"><Button size="sm" data-testid={`delivery-route-${d.event_code}`}><Navigation />Itinéraire</Button></a>
        {!done && <><input ref={input} type="file" hidden multiple accept="image/*" capture="environment" onChange={upload} data-testid={`delivery-photo-input-${d.event_code}`} />
          <Button size="sm" disabled={busy} onClick={() => input.current.click()} data-testid={`delivery-photo-${d.event_code}`}><Camera />{busy ? "Envoi…" : `Photos (${d.photos.length})`}</Button>
          <Button size="sm" className="ml-auto" onClick={() => setSign(true)} data-testid={`delivery-sign-${d.event_code}`}><PenLine />Faire signer le bon</Button></>}
        {done && <Button size="sm" className="ml-auto" onClick={() => openFile(d.bon_file)} data-testid={`delivery-bon-${d.event_code}`}><FileText />Bon de livraison PDF</Button>}
      </div>
      {sign && <SignDialog d={d} onOpenChange={setSign} onDone={reload} />}
    </div>
  );
}

function MissionCard({ m, reload }) {
  const [sign, setSign] = useState(false);
  const input = useRef(null);
  const ko = (err) => toast.error(errMsg(err));
  const signed = !!m.signed_at;
  const dest = encodeURIComponent([m.venue_name, m.venue.address, m.venue.zip, m.venue.city].filter(Boolean).join(" "));
  const upload = async (e) => { for (const file of [...e.target.files]) { const fd = new FormData(); fd.append("file", file); try { await api.post(`/logistics/missions/${m.id}/photos`, fd); } catch (err) { ko(err); } } e.target.value = ""; reload(); };
  const link = () => api.get(`/logistics/missions/${m.id}/tracking-link`).then((r) => { navigator.clipboard?.writeText(r.data.url); toast.success("Lien de suivi copié", { description: r.data.url }); }).catch(ko);
  return (
    <div className="card-soft p-6" data-testid={`mission-card-${m.event_code}-${m.type}`}>
      <div className="flex flex-wrap items-start gap-3"><div className="min-w-0 flex-1"><Link to={`/evenements/${m.event_id}`} className="block truncate text-lg font-semibold hover:underline">{m.event_title}</Link>
        <div className="truncate text-sm text-muted-foreground">{m.type_label} · {[m.venue_name, m.venue.address, m.venue.city].filter(Boolean).join(", ") || "Lieu à définir"}</div></div>
        <span className="rounded-full bg-secondary px-3 py-1 text-xs font-semibold" data-testid={`mission-card-status-${m.event_code}-${m.type}`}>{{ a_planifier: "À planifier", planifiee: "Planifiée", chargee: "Chargée", en_route: "En route", livree: "Livrée", retiree: "Retirée", cloturee: "Clôturée" }[m.status]}</span></div>
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1">
        <Meta icon={Clock}>Arrivée {m.window_start || "?"}{m.depart_at ? ` · départ ${m.depart_at.slice(11)}` : ""}</Meta>
        <Meta icon={Truck}>{m.vehicles.map((v) => `${v.name}${v.drivers.length ? ` (${v.drivers.join(", ")})` : ""}`).join(" · ") || "Sans véhicule"}</Meta>
        {m.eta && m.status === "en_route" && <Meta icon={Navigation} testid={`mission-eta-${m.event_code}`}>Arrivée estimée {m.eta.slice(11)}</Meta>}
        {m.contacts.filter((c) => c.phone).map((c) => <a key={c.name} href={`tel:${c.phone}`}><Meta icon={Phone}>{c.name} · {c.phone}</Meta></a>)}
      </div>
      <div className="mt-3 divide-y divide-border text-sm">{m.items.map((i) => <div key={i.id} className="flex gap-3 py-2"><b className="w-10 shrink-0">{i.qty} ×</b><span className="min-w-0 flex-1 truncate">{i.name}</span><span className="text-[13px] text-[#737373]">{m.vehicles.find((v) => v.id === i.mv_id)?.name || "à placer"}</span></div>)}</div>
      {(m.photos || []).length > 0 && <div className="mt-3 flex flex-wrap gap-2">{m.photos.map((p) => <button key={p} onClick={() => openFile(p)}><FileImg src={p} className="h-20 w-20 rounded-xl object-cover" /></button>)}</div>}
      {signed && <div className="mt-3 text-sm text-muted-foreground" data-testid={`mission-signed-${m.event_code}-${m.type}`}>Signé par <b className="text-foreground">{m.signer_name}</b> le {fmtDate(m.signed_at.slice(0, 10))} à {m.signed_at.slice(11, 16)}{m.sign_notes ? ` — réserves : ${m.sign_notes}` : ""}</div>}
      <div className="mt-4 flex flex-wrap gap-2">
        <a href={`https://www.google.com/maps/dir/?api=1&destination=${dest}`} target="_blank" rel="noreferrer"><Button size="sm"><Navigation />Itinéraire</Button></a>
        <Button size="sm" variant="outline" onClick={link} data-testid={`mission-track-${m.event_code}-${m.type}`}>Lien de suivi</Button>
        {!signed && <>{["a_planifier", "planifiee", "chargee"].includes(m.status) && <Button size="sm" variant="outline" onClick={() => api.patch(`/logistics/missions/${m.id}`, { status: "en_route", confirm: true }).then(reload).catch(ko)} data-testid={`mission-enroute-${m.event_code}-${m.type}`}><Truck />En route</Button>}
          <input ref={input} type="file" hidden multiple accept="image/*" capture="environment" onChange={upload} data-testid={`mission-photo-input-${m.event_code}-${m.type}`} />
          <Button size="sm" onClick={() => input.current.click()}><Camera />Photos ({(m.photos || []).length})</Button>
          <Button size="sm" className="ml-auto" onClick={() => setSign(true)} data-testid={`mission-sign-${m.event_code}-${m.type}`}><PenLine />Faire signer le bon</Button></>}
        {signed && <Button size="sm" className="ml-auto" onClick={() => openFile(m.bon_file)} data-testid={`mission-bon-${m.event_code}-${m.type}`}><FileText />Bon PDF</Button>}
      </div>
      {sign && <SignDialog d={{ id: m.id, event_code: m.event_code, client_name: "", lines: m.items, venue: { name: m.venue_name } }} url={`/logistics/missions/${m.id}/sign`} onOpenChange={setSign} onDone={reload} />}
    </div>
  );
}

export default function Livraison() {
  const [ms, setMs] = useState([]);
  const { can } = useMe();
  const [day, setDay] = useState(dayKey(new Date()));
  const [data, setData] = useState(null);
  const load = useCallback(() => { api.get("/logistics/day", { params: { day } }).then((r) => setMs(r.data.missions)).catch(() => setMs([])); return api.get("/deliveries", { params: { day } }).then((r) => setData(r.data)).catch((err) => toast.error(errMsg(err))); }, [day]);
  useEffect(() => { setData(null); load(); }, [load]);
  const move = async (i, n) => {
    const ids = data.deliveries.map((d) => d.id);
    [ids[i], ids[i + n]] = [ids[i + n], ids[i]];
    try { await api.put("/deliveries/order", { ids }); load(); } catch (err) { toast.error(errMsg(err)); }
  };
  const withMission = new Set(ms.map((m) => m.event_id));
  if (data && !data.all) { data.all = data.deliveries; }
  if (data) data.deliveries = data.all.filter((d) => !withMission.has(d.event_id) || d.status === "livre");
  const done = data?.deliveries.filter((d) => d.status === "livre").length;
  return (
    <div>
      <PageHeader title="Livraison" subtitle={data ? `${data.deliveries.length} livraison(s) le ${fmtDate(day, { weekday: "long", day: "numeric", month: "long" })} — ${done} signée(s).` : "Tournée du jour."} />
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <Button size="icon" onClick={() => setDay(shiftDay(day, -1))} data-testid="delivery-prev-day" aria-label="Jour précédent"><ChevronLeft /></Button>
        <Button onClick={() => setDay(dayKey(new Date()))} data-testid="delivery-today">Aujourd'hui</Button>
        <Button size="icon" onClick={() => setDay(shiftDay(day, 1))} data-testid="delivery-next-day" aria-label="Jour suivant"><ChevronRight /></Button>
        <Input type="date" className="h-10 w-44 rounded-full px-4" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} data-testid="delivery-day-input" />
      </div>
      {ms.length > 0 && <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="mission-delivery-list">{ms.map((m) => <MissionCard key={m.id} m={m} reload={load} />)}</div>}
      {!data ? <Loading /> : !data.deliveries.length ? (ms.length ? null :  <EmptyState icon={Truck} title="Aucune livraison ce jour" text="Les événements confirmés ou en préparation apparaissent ici le jour de leur montage." />) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="delivery-list">
          {data.deliveries.map((d, i) => <Card key={d.id} d={d} idx={i} count={data.deliveries.length} vehicles={data.vehicles} reload={load} move={move} write={can("events:write")} />)}
        </div>
      )}
    </div>
  );
}
