import { useCallback, useEffect, useState } from "react";
import { dual } from "@/components/catalogue/Units";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Trash2, Plus, Pencil, Download, Printer, ArrowLeftRight, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { PageHeader, Loading, Field, EmptyState } from "@/components/common";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { fmtDate } from "@/lib/constants";
import { TrashDialog } from "@/components/Trash";
import { useMe } from "@/context/MeContext";
import { DOT } from "@/components/stock/Availability";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm";
const TYPES = { principal: "Entrepôt principal", site_client: "Dépôt sur site client", partenaire: "Dépôt partenaire", vehicule: "Véhicule-stock", autre: "Autre" };
const BLANK = { name: "", type: "autre", address: "", postal_code: "", city: "", country: "France", venue_id: "", access_hours: "", access_instructions: "", is_default: false, priority: 10, restricted_to_venue: false, active: true };
const th = "px-4 py-3 text-left text-xs font-semibold text-muted-foreground";
const td = "px-4 py-2.5";

function WarehouseDialog({ value, venues, onClose, onSaved }) {
  const [f, setF] = useState(BLANK);
  useEffect(() => { if (value) setF({ ...BLANK, ...value }); }, [value]);
  if (!value) return null;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const submit = (e) => { e.preventDefault(); const body = { ...f, priority: Number(f.priority) || 0, lat: f.lat ?? null, lng: f.lng ?? null }; (f.id ? api.put(`/warehouses/${f.id}`, body) : api.post("/warehouses", body)).then(() => { toast.success("Entrepôt enregistré"); onSaved(); onClose(); }).catch(ko); };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto">
        <DialogHeader><DialogTitle className="text-xl font-bold">{f.id ? "Modifier l'entrepôt" : "Nouvel entrepôt"}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-4" data-testid="warehouse-form">
          <Field label="Nom"><Input required value={f.name} onChange={set("name")} data-testid="warehouse-name" /></Field>
          <Field label="Type"><select className={sel} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value, restricted_to_venue: e.target.value === "site_client" })} data-testid="warehouse-type">{Object.entries(TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Lieu lié (dépôt sur site)" className="col-span-2"><select className={sel} value={f.venue_id} onChange={set("venue_id")} data-testid="warehouse-venue"><option value="">Aucun</option>{venues.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select></Field>
          <Field label="Adresse" className="col-span-2"><Input value={f.address} onChange={set("address")} /></Field>
          <Field label="Code postal"><Input value={f.postal_code} onChange={set("postal_code")} /></Field><Field label="Ville"><Input value={f.city} onChange={set("city")} /></Field>
          <Field label="Horaires d'accès"><Input value={f.access_hours} onChange={set("access_hours")} /></Field><Field label="Priorité de prélèvement (0 = d'abord)"><Input type="number" min="0" value={f.priority} onChange={set("priority")} data-testid="warehouse-priority" /></Field>
          <Field label="Instructions" className="col-span-2"><Textarea rows={2} value={f.access_instructions} onChange={set("access_instructions")} /></Field>
          <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f.restricted_to_venue} onChange={set("restricted_to_venue")} data-testid="warehouse-restricted" />Stock utilisable uniquement pour les événements sur ce lieu (sinon : partout, transfert nécessaire)</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f.is_default} onChange={set("is_default")} data-testid="warehouse-default" />Entrepôt par défaut</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!f.active} onChange={set("active")} data-testid="warehouse-active" />Actif (décocher = archivé)</label>
          <DialogFooter className="col-span-2"><Button data-testid="warehouse-submit">Enregistrer</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function StockView({ wh, whs, write, onChanged }) {
  const [d, setD] = useState(null);
  const [q, setQ] = useState("");
  const [counts, setCounts] = useState(null);
  const [tr, setTr] = useState(null);
  const load = useCallback(() => api.get(`/warehouses/${wh.id}/stock`).then((r) => setD(r.data)).catch(ko), [wh.id]);
  useEffect(() => { setCounts(null); load(); }, [load]);
  if (!d) return <Loading />;
  const rows = d.rows.filter((r) => (counts || r.qty_on_hand > 0 || q) && (!q || `${r.ref} ${r.name}`.toLowerCase().includes(q.toLowerCase())));
  const done = () => { load(); onChanged(); };
  const validate = () => api.post("/stock/inventory", { warehouse_id: wh.id, counts: Object.entries(counts).filter(([, v]) => v !== "").map(([product_id, v]) => ({ product_id, counted: Number(v) })) }).then((r) => { toast.success(`Inventaire validé : ${r.data.adjusted} ajustement(s)`); setCounts(null); done(); }).catch(ko);
  const send = () => api.post("/stock/transfers", { product_id: tr.product_id, qty: Number(tr.qty), from_warehouse_id: wh.id, to_warehouse_id: tr.to, in_transit: tr.in_transit, note: tr.note || "" }).then(() => { toast.success("Transfert enregistré"); setTr(null); done(); }).catch(ko);
  return (
    <div data-testid="warehouse-stock">
      <div className="mb-3 flex flex-wrap items-center gap-2 print:hidden">
        <Input className="w-56" placeholder="Rechercher un produit…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="warehouse-stock-search" />
        <Button size="sm" variant="outline" onClick={() => downloadPdf(`/warehouses/${wh.id}/stock?format=csv`, `inventaire-${wh.name}.csv`).catch(ko)} data-testid="warehouse-stock-csv"><Download />CSV</Button>
        <Button size="sm" variant="outline" onClick={() => window.print()} data-testid="warehouse-stock-print"><Printer />Imprimer</Button>
        {write && (counts ? <><Button size="sm" onClick={validate} data-testid="inventory-validate">Valider l'inventaire</Button><Button size="sm" variant="ghost" onClick={() => setCounts(null)}>Annuler</Button></> : <Button size="sm" variant="outline" onClick={() => setCounts({})} data-testid="inventory-start">Inventaire</Button>)}
      </div>
      <div className="card-soft overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-border"><th className={th}>Référence</th><th className={th}>Produit</th><th className={th}>En stock</th><th className={th}>Maint. / HS</th>{counts && <><th className={th}>Compté</th><th className={th}>Écart</th></>}<th className={th} /></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.product_id} className="border-b border-border last:border-0" data-testid={`stock-row-${r.ref}`}><td className={`${td} font-mono text-xs`}>{r.ref}</td><td className={td}>{r.name}</td><td className={`${td} font-semibold`} data-testid={`stock-qty-${r.ref}`}>{r.secondary_uom || (r.stock_uom && r.stock_uom !== "piece") ? dual(r, r.qty_on_hand) : r.qty_on_hand}</td><td className={td}>{r.maintenance}</td>
            {counts && <><td className={td}><Input type="number" min="0" step="any" className="h-8 w-24" value={counts[r.product_id] ?? ""} onChange={(e) => setCounts({ ...counts, [r.product_id]: e.target.value })} data-testid={`inventory-count-${r.ref}`} /></td><td className={td}>{counts[r.product_id] ? Number(counts[r.product_id]) - r.qty_on_hand : ""}</td></>}
            <td className={`${td} text-right print:hidden`}>{write && !counts && r.qty_on_hand > 0 && whs.length > 1 && <Button size="sm" variant="ghost" onClick={() => setTr({ product_id: r.product_id, name: r.name, qty: 1, to: whs.find((x) => x.id !== wh.id).id, in_transit: false })} data-testid={`transfer-${r.ref}`}><ArrowLeftRight />Transférer</Button>}</td></tr>))}
          {!rows.length && <tr><td className={td} colSpan={7}>Aucun produit dans cet entrepôt.</td></tr>}</tbody></table></div>
      {tr && <Dialog open onOpenChange={() => setTr(null)}><DialogContent className="max-w-md"><DialogHeader><DialogTitle>Transférer {tr.name}</DialogTitle></DialogHeader>
        <Field label="Quantité"><Input type="number" min="0" step="any" value={tr.qty} onChange={(e) => setTr({ ...tr, qty: e.target.value })} data-testid="transfer-qty" /></Field>
        <Field label={`De ${wh.name} vers`}><select className={sel} value={tr.to} onChange={(e) => setTr({ ...tr, to: e.target.value })} data-testid="transfer-to">{whs.filter((x) => x.id !== wh.id).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={tr.in_transit} onChange={(e) => setTr({ ...tr, in_transit: e.target.checked })} data-testid="transfer-transit" />En transit (à réceptionner à l'arrivée)</label>
        <DialogFooter><Button onClick={send} data-testid="transfer-submit">Transférer</Button></DialogFooter></DialogContent></Dialog>}
    </div>
  );
}

function Movements({ write }) {
  const [rows, setRows] = useState(null);
  const load = useCallback(() => api.get("/stock/movements").then((r) => setRows(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!rows) return <Loading />;
  return <div className="card-soft overflow-x-auto" data-testid="movements-table"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b border-border"><th className={th}>Date</th><th className={th}>Type</th><th className={th}>Produit</th><th className={th}>Qté</th><th className={th}>De → vers</th><th className={th}>Par</th><th className={th}>Note</th></tr></thead>
    <tbody>{rows.map((m) => <tr key={m.id} className="border-b border-border last:border-0"><td className={td}>{new Date(m.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td><td className={td}>{m.type_label}{m.status === "in_transit" && <> · <b className="text-amber-600">en transit</b> {write && <button className="underline" onClick={() => api.post(`/stock/transfers/${m.id}/receive`).then(load).catch(ko)} data-testid={`receive-${m.id}`}>réceptionner</button>}</>}</td><td className={td}>{m.product}</td><td className={`${td} font-semibold`}>{m.qty}</td><td className={td}>{[m.from_name, m.to_name].filter(Boolean).join(" → ") || "—"}</td><td className={td}>{m.user}</td><td className={td}>{m.note}</td></tr>)}</tbody></table></div>;
}

function Options() {
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/stock/options").then((r) => setD(r.data)).catch(ko); }, []);
  if (!d) return <Loading />;
  if (!d.rows.length) return <EmptyState title="Aucune option en cours" text="Les devis non validés portant sur du matériel daté apparaissent ici." />;
  return <div data-testid="options-view"><p className="mb-3 text-sm text-muted-foreground">{d.rule}</p><div className="card-soft divide-y divide-border">{d.rows.map((r, i) => (
    <div key={i} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm" data-testid={`option-row-${r.number}`}><span className={`h-2.5 w-2.5 rounded-full ${DOT[r.color]}`} /><b>{r.product}</b><span>{fmtDate(r.date)}</span><Link className="underline" to={`/evenements/${r.event_id}`}>{r.number}</Link><span>{r.client}</span><span>{r.qty} demandé(s) · {r.available_now} dispo</span>
      {r.competitors.length > 0 && <span className="text-xs text-muted-foreground">concurrents : {r.competitors.join(", ")}</span>}{r.expires && <span className="text-xs text-muted-foreground">option jusqu'au {fmtDate(r.expires)}</span>}{r.message && <span className="w-full text-xs font-semibold">{r.message}</span>}</div>))}</div></div>;
}

export default function Entrepots() {
  const { can } = useMe();
  const write = can("catalog:write");
  const [sp, setSp] = useSearchParams();
  const vue = sp.get("vue") || "entrepots";
  const [whs, setWhs] = useState(null);
  const [venues, setVenues] = useState([]);
  const [edit, setEdit] = useState(null);
  const [trash, setTrash] = useState(null);
  const [cur, setCur] = useState(null);
  const [imp, setImp] = useState(null);
  const load = useCallback(() => api.get("/warehouses").then((r) => { setWhs(r.data); setCur((c) => c || r.data.find((w) => w.is_default)?.id || r.data[0]?.id); }).catch(ko), []);
  useEffect(() => { load(); api.get("/venues").then((r) => setVenues(r.data)).catch(() => {}); }, [load]);
  if (!whs) return <Loading />;
  const wh = whs.find((w) => w.id === cur);
  const tabs = [["entrepots", "Entrepôts & stock"], ["mouvements", "Mouvements"], ...(can("finance:read") ? [["options", "Options en cours"]] : [])];
  const doImport = () => api.post("/stock/import", { text: imp }).then((r) => { toast.success(`${r.data.imported} ligne(s) importée(s)`); r.data.errors.slice(0, 5).forEach((e) => toast.error(e)); setImp(null); load(); setCur((c) => c); }).catch(ko);
  return (
    <div data-testid="warehouses-page">
      <PageHeader title="Entrepôts & stocks" subtitle="Stock par produit et par emplacement, transferts, inventaire et options en cours."
        actions={write && <><Button variant="outline" onClick={() => setImp("")} data-testid="stock-import-button"><Upload />Import CSV</Button><Button onClick={() => setEdit(BLANK)} data-testid="new-warehouse-button"><Plus />Entrepôt</Button></>} />
      <div className="mb-5 inline-flex rounded-full border border-border bg-card p-1 print:hidden">{tabs.map(([k, l]) => <button key={k} onClick={() => setSp(k === "entrepots" ? {} : { vue: k })} data-testid={`warehouses-tab-${k}`} className={`rounded-full px-4 py-1.5 text-xs font-semibold ${vue === k ? "bg-foreground text-background" : "text-muted-foreground"}`}>{l}</button>)}</div>
      {vue === "mouvements" ? <Movements write={write} /> : vue === "options" ? <Options /> : (<>
        <div className="mb-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3 print:hidden">{whs.map((w) => (
          <div key={w.id} role="button" tabIndex={0} onClick={() => setCur(w.id)} onKeyDown={(e) => e.key === "Enter" && setCur(w.id)} className={`card-soft cursor-pointer p-4 ${cur === w.id ? "ring-2 ring-primary" : ""} ${w.active ? "" : "opacity-60"}`} data-testid={`warehouse-card-${w.name}`}>
            <div className="flex items-start justify-between gap-2"><div><div className="font-semibold">{w.name}</div><div className="text-xs text-muted-foreground">{TYPES[w.type]}{w.is_default ? " · par défaut" : ""}{w.venue_name ? ` · ${w.venue_name}` : ""}{w.restricted_to_venue ? " · réservé à ce lieu" : ""}{w.active ? "" : " · archivé"}</div></div>
              {write && <button className="icon-btn" onClick={(e) => { e.stopPropagation(); setEdit(w); }} aria-label="Modifier" data-testid={`warehouse-edit-${w.name}`}><Pencil className="h-4 w-4" /></button>}{write && <button className="icon-btn text-red-600" onClick={(e) => { e.stopPropagation(); setTrash(w); }} aria-label="Supprimer" data-testid={`warehouse-delete-${w.name}`}><Trash2 className="h-4 w-4" /></button>}</div>
            <div className="mt-2 text-sm">{w.products} produit(s) · {w.units} unité(s)</div></div>))}</div>
        {wh && <><h2 className="mb-3 text-base font-semibold md:text-lg">Inventaire — {wh.name}</h2><StockView key={wh.id + whs.reduce((n, w) => n + w.units, 0)} wh={wh} whs={whs.filter((w) => w.active)} write={write} onChanged={load} /></>}
      </>)}
      <WarehouseDialog value={edit} venues={venues} onClose={() => setEdit(null)} onSaved={load} />
      {imp !== null && <Dialog open onOpenChange={() => setImp(null)}><DialogContent className="max-w-lg"><DialogHeader><DialogTitle>Import CSV du stock</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">Une ligne par stock : référence (ou nom) ; entrepôt ; quantité. La quantité remplace le stock de cet entrepôt. Ex. « Chaise bistro ; Dépôt Valbonne ; 150 ».</p>
        <Textarea rows={8} value={imp} onChange={(e) => setImp(e.target.value)} data-testid="stock-import-text" />
        <input type="file" accept=".csv,text/csv" onChange={(e) => e.target.files[0]?.text().then(setImp)} data-testid="stock-import-file" />
        <DialogFooter><Button disabled={!imp.trim()} onClick={doImport} data-testid="stock-import-submit">Importer</Button></DialogFooter></DialogContent></Dialog>}
      {trash && <TrashDialog items={[{ kind: "warehouse", id: trash.id, name: trash.name }]} onClose={() => setTrash(null)} onDone={load} />}
    </div>
  );
}
