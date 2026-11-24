import { useCallback, useEffect, useRef, useState } from "react";
import { TrashBtn, Pick, BulkDelete } from "@/components/Trash";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import L from "leaflet";
import { Plus, MapPin, Truck, Zap, Volume2, Clock, Users, Navigation, Pencil, LocateFixed, Map as MapIcon, Image as ImageIcon } from "lucide-react";
import { Meta, SearchPill } from "@/components/common";
import { FileImg, FileList, openFile } from "@/lib/files";
import { Trash2, LayoutPanelTop } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PageHeader, Loading, Field, StatusBadge, Info } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { OnsiteEditor, OnsiteList } from "@/components/events/OnsiteContacts";

function VenueMap({ venues, active, onSelect }) {
  const el = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);
  useEffect(() => {
    map.current = L.map(el.current, { scrollWheelZoom: false }).setView([43.6, 5.6], 8);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap" }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => { map.current.remove(); };
  }, []);
  useEffect(() => {
    layer.current.clearLayers();
    const pts = venues.filter((v) => v.lat != null && v.lng != null);
    pts.forEach((v) => {
      const icon = L.divIcon({ className: "", html: `<div class="venue-pin ${v.id === active ? "active" : ""}"></div>`, iconSize: [28, 28], iconAnchor: [14, 28] });
      L.marker([v.lat, v.lng], { icon }).addTo(layer.current).bindTooltip(v.name).on("click", () => onSelect(v.id));
    });
    if (pts.length) map.current.fitBounds(pts.map((v) => [v.lat, v.lng]), { padding: [40, 40], maxZoom: 12 });
  }, [venues, active, onSelect]);
  return <div ref={el} className="h-full min-h-[420px] w-full rounded-2xl border border-border" data-testid="venues-map" />;
}

const EMPTY = { name: "", type: "Domaine", address: "", zip: "", city: "", lat: null, lng: null, capacity: 0, contact_name: "", contact_phone: "", contact_email: "", onsite_contacts: [], truck_access: "", electricity: "", power_capacity_w: 0, sound_limiter: "", setup_hours: "", teardown_hours: "", access_instructions: "", photos: [], plans: [], sections: [], notes: "" };

function VenueDialog({ open, onOpenChange, venue, onSaved }) {
  const [f, setF] = useState(EMPTY);
  const [geo, setGeo] = useState([]);
  useEffect(() => { if (open) { setF(venue ? Object.fromEntries(Object.keys(EMPTY).map((k) => [k, venue[k] ?? EMPTY[k]])) : EMPTY); setGeo([]); } }, [open, venue]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const locate = async () => {
    try { const r = await api.get("/geocode", { params: { q: [f.address, f.zip, f.city].filter(Boolean).join(" ") || f.name } }); setGeo(r.data); if (!r.data.length) toast.info("Adresse introuvable"); } catch (err) { toast.error(errMsg(err)); }
  };
  const submit = async (e) => {
    e.preventDefault();
    const body = { ...f, capacity: Number(f.capacity) || 0, lat: f.lat === "" || f.lat == null ? null : Number(f.lat), lng: f.lng === "" || f.lng == null ? null : Number(f.lng), photos: f.photos.filter(Boolean), plans: f.plans.filter(Boolean), sections: f.sections.filter((s) => s.name.trim()).map((s) => ({ ...s, id: s.id || "", name: s.name.trim(), notes: s.notes || "", transfer_minutes: Number(s.transfer_minutes) || 0 })) };
    try { venue ? await api.put(`/venues/${venue.id}`, body) : await api.post("/venues", body); toast.success("Lieu enregistré"); onSaved(); onOpenChange(false); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{venue ? "Modifier le lieu" : "Nouveau lieu"}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-4" data-testid="venue-form">
          <Field label="Nom"><Input required value={f.name} onChange={set("name")} data-testid="venue-name-input" /></Field>
          <Field label="Type"><Input value={f.type} onChange={set("type")} placeholder="Domaine, château, salle…" /></Field>
          <Field label="Adresse" className="col-span-2"><Input value={f.address} onChange={set("address")} data-testid="venue-address-input" /></Field>
          <Field label="Code postal"><Input value={f.zip} onChange={set("zip")} /></Field>
          <Field label="Ville"><Input value={f.city} onChange={set("city")} data-testid="venue-city-input" /></Field>
          <div className="col-span-2 flex flex-wrap items-end gap-2">
            <Field label="Latitude"><Input value={f.lat ?? ""} onChange={set("lat")} className="w-36" data-testid="venue-lat-input" /></Field>
            <Field label="Longitude"><Input value={f.lng ?? ""} onChange={set("lng")} className="w-36" data-testid="venue-lng-input" /></Field>
            <Button type="button" variant="outline" onClick={locate} data-testid="venue-geocode-button"><LocateFixed className="mr-1.5 h-4 w-4" />Localiser l'adresse</Button>
          </div>
          {geo.length > 0 && <div className="col-span-2 space-y-1">{geo.map((g, i) => <button type="button" key={i} onClick={() => { setF({ ...f, lat: g.lat, lng: g.lng }); setGeo([]); }} className="block w-full rounded-lg border border-border px-3 py-2 text-left text-xs hover:bg-secondary">{g.label}</button>)}</div>}
          <Field label="Capacité (personnes)"><Input type="number" min="0" value={f.capacity} onChange={set("capacity")} /></Field>
          <div className="col-span-2"><OnsiteEditor value={f.onsite_contacts || []} onChange={(v) => setF((cur) => ({ ...cur, onsite_contacts: v }))} /></div>
          <Field label="Accès camion" className="col-span-2"><Input value={f.truck_access} onChange={set("truck_access")} /></Field>
          <Field label="Instructions d'accès / livraison" className="col-span-2"><Textarea rows={2} value={f.access_instructions} onChange={set("access_instructions")} data-testid="venue-instructions-input" /></Field>
          <Field label="Électricité disponible"><Input value={f.electricity} onChange={set("electricity")} /></Field>
          <Field label="Capacité électrique (W, pour l'alerte)"><Input type="number" min="0" value={f.power_capacity_w || 0} onChange={(e) => setF({ ...f, power_capacity_w: Number(e.target.value) || 0 })} data-testid="venue-power-capacity-input" /></Field>
          <Field label="Limiteur de son"><Input value={f.sound_limiter} onChange={set("sound_limiter")} /></Field>
          <Field label="Horaires de montage"><Input value={f.setup_hours} onChange={set("setup_hours")} /></Field>
          <Field label="Horaires de démontage"><Input value={f.teardown_hours} onChange={set("teardown_hours")} /></Field>
          <FileList label="Photos" value={f.photos} onChange={(photos) => setF({ ...f, photos })} testid="venue-photos" />
          <FileList label="Plans" value={f.plans} onChange={(plans) => setF({ ...f, plans })} testid="venue-plans" />
          <div className="col-span-2" data-testid="venue-sections">
            <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-muted-foreground">Espaces du lieu (ex. La Folie, Le Temple, La piscine)</span>
              <Button type="button" size="sm" onClick={() => setF({ ...f, sections: [...f.sections, { id: "", name: "", notes: "" }] })} data-testid="venue-add-section"><Plus />Espace</Button></div>
            {f.sections.map((s, i) => (
              <div key={i} className="mb-2 flex gap-2">
                <Input placeholder="Nom de l'espace" value={s.name} onChange={(e) => setF({ ...f, sections: f.sections.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} data-testid={`venue-section-name-${i}`} />
                <Input placeholder="Notes (accès, électricité…)" value={s.notes} onChange={(e) => setF({ ...f, sections: f.sections.map((x, j) => (j === i ? { ...x, notes: e.target.value } : x)) })} />
                <Input className="w-28 shrink-0" type="number" min="0" max="240" placeholder="Bascule (20)" title="Temps de bascule en minutes pour amener du matériel réemployé vers cet espace (vide = 20 min)" value={s.transfer_minutes || ""} onChange={(e) => setF({ ...f, sections: f.sections.map((x, j) => (j === i ? { ...x, transfer_minutes: e.target.value } : x)) })} data-testid={`venue-section-transfer-${i}`} />
                <Button type="button" size="icon" variant="ghost" onClick={() => setF({ ...f, sections: f.sections.filter((_, j) => j !== i) })}><Trash2 /></Button>
              </div>
            ))}
          </div>
          <Field label="Notes" className="col-span-2"><Textarea rows={2} value={f.notes} onChange={set("notes")} /></Field>
          <DialogFooter className="col-span-2"><Button data-testid="venue-form-submit">Enregistrer</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const Spec = ({ icon: I, label, value }) => <div className="flex gap-3"><I className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><div><div className="eyebrow">{label}</div><div className="text-sm">{value || "—"}</div></div></div>;

function VenueSheet({ id, onOpenChange, onEdit, write }) {
  const [v, setV] = useState(null);
  useEffect(() => { setV(null); if (id) api.get(`/venues/${id}`).then((r) => setV(r.data)); }, [id]);
  const dest = v?.lat != null ? `${v.lat},${v.lng}` : encodeURIComponent(`${v?.address} ${v?.city}`);
  return (
    <Sheet open={!!id} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto p-0 sm:max-w-lg">
        {v?.photos?.[0] && <FileImg src={v.photos[0]} alt={v.name} className="h-52 w-full object-cover" />}
        <div className="p-6">
          <SheetHeader><SheetTitle className="font-display text-2xl font-medium">{v?.name || "…"}</SheetTitle></SheetHeader>
          {v && (
            <div className="mt-2 space-y-5" data-testid="venue-sheet">
              <div className="text-sm text-muted-foreground">{v.type} · {v.address}, {v.zip} {v.city}</div>
              <div className="flex flex-wrap gap-2">
                <a href={`https://www.google.com/maps/dir/?api=1&destination=${dest}`} target="_blank" rel="noreferrer"><Button size="sm" data-testid="venue-route-google"><Navigation className="mr-1.5 h-3.5 w-3.5" />Itinéraire Google Maps</Button></a>
                {v.lat != null && <a href={`https://waze.com/ul?ll=${v.lat},${v.lng}&navigate=yes`} target="_blank" rel="noreferrer"><Button size="sm" variant="outline" data-testid="venue-route-waze">Waze</Button></a>}
                {write && <Button size="sm" variant="ghost" onClick={() => onEdit(v)} data-testid="edit-venue-button"><Pencil className="mr-1 h-3.5 w-3.5" />Modifier</Button>}
              </div>
              <div className="grid grid-cols-1 gap-4">
                <Spec icon={Users} label="Capacité" value={v.capacity ? `${v.capacity} personnes` : ""} />
                <Spec icon={Truck} label="Accès camion" value={v.truck_access} />
                <Spec icon={Zap} label="Électricité" value={v.electricity} />
                <Spec icon={Volume2} label="Limiteur de son" value={v.sound_limiter} />
                <Spec icon={Clock} label="Montage / démontage" value={[v.setup_hours, v.teardown_hours].filter(Boolean).join(" · ")} />
              </div>
              <div className="grid grid-cols-2 gap-4"><div className="col-span-2"><OnsiteList contacts={v.onsite_contacts || []} /></div>{v.access_instructions && <div className="col-span-2"><Info label="Instructions d'accès / livraison" value={v.access_instructions} /></div>}</div>
              {v.notes && <p className="rounded-lg bg-secondary p-3 text-sm">{v.notes}</p>}
              {v.sections?.length > 0 && <div data-testid="venue-sheet-sections"><div className="eyebrow mb-2">Espaces ({v.sections.length})</div>
                {v.sections.map((s) => <div key={s.id} className="flex gap-3 py-1.5 text-sm"><LayoutPanelTop className="mt-0.5 h-[18px] w-[18px] shrink-0" /><div><b>{s.name}</b>{s.notes && <div className="text-muted-foreground">{s.notes}</div>}</div></div>)}</div>}
              {(v.plans?.length > 0 || v.photos?.length > 1) && <div className="grid grid-cols-2 gap-x-4"><FileList label="Plans" value={v.plans || []} readOnly testid="venue-sheet-plans" /><FileList label="Photos" value={v.photos || []} readOnly testid="venue-sheet-photos" /></div>}
              <div><div className="eyebrow mb-2">Événements sur ce lieu ({v.events.length})</div>
                {v.events.map((e) => <Link key={e.id} to={`/evenements/${e.id}`} className="flex items-center justify-between rounded-lg px-2 py-2 hover:bg-secondary"><div><div className="text-sm font-medium">{e.title}</div><div className="text-xs text-muted-foreground">{fmtDate(e.start)}</div></div><StatusBadge status={e.status} /></Link>)}</div>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default function Venues() {
  const { can } = useMe();
  const write = can("venues:write");
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState(null);
  const [edit, setEdit] = useState(null);
  const load = () => api.get("/venues").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  const openId = params.get("id");
  const select = useCallback((id) => setParams({ id }), [setParams]);
  const [q, setQ] = useState("");
  const shown = (rows || []).filter((v) => !q || `${v.name} ${v.address} ${v.zip} ${v.city}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      <PageHeader title="Lieux" subtitle={`${rows?.length ?? 0} lieu(x) récurrent(s) — plans et positions matériel.`}
        actions={write && <Button onClick={() => setEdit({})} data-testid="new-venue-button"><Plus />Lieu</Button>} />
      <div className="mb-6"><SearchPill value={q} onChange={setQ} placeholder="Rechercher un lieu…" testid="venues-search-input" /></div>
      {!rows ? <Loading /> : (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.5fr_1fr]">
          <div className="grid grid-cols-1 content-start gap-4 md:grid-cols-2" data-testid="venues-list">
            {shown.map((v) => (
              <button key={v.id} onClick={() => select(v.id)} className={`card-soft hover-lift p-6 text-left ${openId === v.id ? "!border-foreground" : ""}`} data-testid={`venue-card-${v.id}`}>
                <div className="flex gap-4">
                  <MapPin className="mt-1 h-5 w-5 shrink-0" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 truncate text-lg font-semibold">{v.name}<TrashBtn kind="venue" id={v.id} name={v.name} onDone={load} /></div>
                    <div className="truncate text-sm text-muted-foreground">{[v.address, [v.zip, v.city].filter(Boolean).join(" "), "France"].filter(Boolean).join(", ")}</div>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1">
                  {v.capacity > 0 && <Meta icon={Users}>{v.capacity} pers.</Meta>}
                  <Meta icon={MapIcon}>{(v.plans || []).length} plan(s)</Meta>
                  <Meta icon={ImageIcon}>{(v.photos || []).length} photo(s)</Meta>
                  {v.sections?.length > 0 && <Meta icon={LayoutPanelTop}>{v.sections.length} espace(s)</Meta>}
                </div>
              </button>
            ))}
            {!shown.length && <div className="text-sm text-muted-foreground">Aucun lieu ne correspond à la recherche.</div>}
          </div>
          <div className="h-[420px] xl:sticky xl:top-6 xl:h-[calc(100vh-180px)]"><VenueMap venues={shown} active={openId} onSelect={select} /></div>
        </div>
      )}
      <VenueDialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)} venue={edit?.id ? edit : null} onSaved={load} />
      <VenueSheet id={openId} write={write} onOpenChange={(o) => !o && setParams({})} onEdit={(v) => { setParams({}); setEdit(v); }} />
    </div>
  );
}
