import { useCallback, useEffect, useState } from "react";
import { TrashBtn, Pick, BulkDelete } from "@/components/Trash";
import { Link, useSearchParams } from "react-router-dom";
import { dual, TemplatesDialog } from "@/components/catalogue/Units";
import { KitEditor } from "@/components/catalogue/Kits";
import { Plus, Search, Wrench, CalendarRange, Pencil, FileText, FileDown, Speaker, Lightbulb, Box, Monitor, Disc3, Zap, Armchair } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader, Loading, ModuleBadge, EmptyState, Field } from "@/components/common";
import { EquipmentDialog, MaintenanceDialog, BookingsSheet, PackDialog } from "@/components/catalogue/CatalogueDialogs";
import { ProductSheetDialog } from "@/components/catalogue/Material";
import { StockDialog } from "@/components/stock/Availability";
import { api } from "@/lib/api";
import { CATEGORIES, fmtEur, toLocalInput } from "@/lib/constants";
import { PackComposition } from "@/components/billing/PackParts";
import { PackApply, PackTranslations } from "@/components/catalogue/PackI18n";
import { useMe } from "@/context/MeContext";
import { FileImg, openFile } from "@/lib/files";

const CAT_ICON = { Sonorisation: Speaker, "Éclairage": Lightbulb, Structure: Box, "Vidéo & Bornes": Monitor, DJ: Disc3, "Énergie": Zap, Mobilier: Armchair };

function Gauge({ item }) {
  const t = item.qty_total || 1;
  const pct = (n) => `${(n / t) * 100}%`;
  return (
    <div className="w-32">
      <div className="flex h-2 overflow-hidden rounded-full bg-secondary">
        <div className="bg-emerald-500" style={{ width: pct(Math.max(0, item.available)) }} />
        <div className="bg-primary/70" style={{ width: pct(item.reserved) }} />
        <div className="bg-amber-500" style={{ width: pct(item.qty_maintenance) }} />
      </div>
      <div className={`mt-1 text-xs ${item.available <= 0 ? "font-semibold text-red-700" : "text-muted-foreground"}`}>{item.available} / {item.qty_total} dispo{item.secondary_uom && item.qty_per_piece ? ` · ${Math.round(item.available * item.qty_per_piece * 1000) / 1000} ${item.secondary_uom}` : ""}</div>
    </div>
  );
}

function Inventory({ write, finance }) {
  const [pack, setPack] = useState(null);
  const [ptr, setPtr] = useState(null);
  const [papply, setPapply] = useState(null);
  const [params] = useSearchParams();
  const now = new Date();
  const [period, setPeriod] = useState({ start: toLocalInput(now), end: toLocalInput(new Date(now.getTime() + 86400000)) });
  const [data, setData] = useState(null);
  const [q, setQ] = useState(params.get("q") || "");
  const [cat, setCat] = useState("all");
  const [fl, setFl] = useState({ sub: "", type: "", prov: "", noPrice: false, noStock: false, attr: "", attrVal: "" });
  const [tpls, setTpls] = useState([]);
  const [tplOpen, setTplOpen] = useState(false);
  const [kitOpen, setKitOpen] = useState(false);
  const [pick, setPick] = useState([]);
  const loadTpls = useCallback(() => api.get("/attribute-templates").then((r) => setTpls(r.data)).catch(() => {}), []);
  useEffect(() => { loadTpls(); }, [loadTpls]);
  const attrFields = Object.values(Object.fromEntries(tpls.flatMap((t) => t.fields).map((x) => [x.code, x])));
  const attrOk = (i) => { if (!fl.attr || fl.attrVal === "") return true; const v = i.attributes?.[fl.attr]; if (v == null) return false; return typeof v === "number" ? v >= Number(fl.attrVal) : String(v).toLowerCase().includes(fl.attrVal.toLowerCase()); };
  const { me } = useMe();
  const [edit, setEdit] = useState(null);
  const [maint, setMaint] = useState(null);
  const [book, setBook] = useState(null);
  const [sheet, setSheet] = useState(null);
  const [sup, setSup] = useState({ rows: [], allowed: false });
  useEffect(() => { api.get("/supplier-products").then((r) => setSup(r.data)).catch(() => {}); }, [sheet]);
  const [prim, setPrim] = useState({});
  const loadDocs = useCallback(() => api.get("/product-documents").then((r) => setPrim(Object.fromEntries(r.data.filter((d) => d.is_primary).flatMap((d) => d.product_ids.map((i) => [i, d]))))).catch(() => {}), []);
  useEffect(() => { loadDocs(); }, [loadDocs]);
  const { can } = useMe();
  const [stockOf, setStockOf] = useState(null);
  const load = useCallback(() => { if (period.start && period.end > period.start) api.get("/equipment", { params: period }).then((r) => setData(r.data)); }, [period]);
  useEffect(() => { load(); }, [load]);
  const all = data?.items || [];
  const uniq = (k, src = all) => [...new Set(src.map((i) => i[k]).filter(Boolean))].sort();
  const items = all.filter((i) => (cat === "all" || i.category === cat) && (!fl.sub || i.subcategory === fl.sub) && (!fl.type || (i.product_type || "Location") === fl.type) && (!fl.prov || i.provenance === fl.prov)
    && (!fl.sup || sup.rows.some((m) => m.product_id === i.id && m.supplier_id === fl.sup)) && attrOk(i) && (!fl.noPrice || i.price_day == null) && (!fl.noStock || !i.qty_total) && (!fl.todo || i.to_complete) && (!q || `${i.ref} ${i.name}`.toLowerCase().includes(q.toLowerCase())));
  const fsel = "h-10 rounded-lg border border-border bg-card px-2 text-sm";
  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Disponibilité du"><Input type="datetime-local" className="bg-card" value={period.start} onChange={(e) => setPeriod({ ...period, start: e.target.value })} data-testid="availability-start-input" /></Field>
        <Field label="au"><Input type="datetime-local" className="bg-card" value={period.end} onChange={(e) => setPeriod({ ...period, end: e.target.value })} data-testid="availability-end-input" /></Field>
        <div className="relative w-56"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input className="bg-card pl-9" placeholder="Référence, nom…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="equipment-search-input" /></div>
        <Select value={cat} onValueChange={setCat}><SelectTrigger className="w-44 bg-card" data-testid="equipment-category-filter"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Toutes catégories</SelectItem>{[...new Set([...CATEGORIES, ...uniq("category")])].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent></Select>
        <select className={fsel} value={fl.sub} onChange={(e) => setFl({ ...fl, sub: e.target.value })} data-testid="equipment-subcategory-filter"><option value="">Toutes sous-catégories</option>{uniq("subcategory", all.filter((i) => cat === "all" || i.category === cat)).map((c) => <option key={c}>{c}</option>)}</select>
        <select className={fsel} value={fl.type} onChange={(e) => setFl({ ...fl, type: e.target.value })} data-testid="equipment-type-filter"><option value="">Tous types</option>{["Location", "Consommable", "Service", "Prestation artistique", "Pack"].map((c) => <option key={c}>{c}</option>)}</select>
        <select className={fsel} value={fl.prov} onChange={(e) => setFl({ ...fl, prov: e.target.value })} data-testid="equipment-provenance-filter"><option value="">Toutes provenances</option>{uniq("provenance").map((c) => <option key={c}>{c}</option>)}</select>
        <label className="flex h-10 items-center gap-1 text-sm"><input type="checkbox" checked={fl.noPrice} onChange={(e) => setFl({ ...fl, noPrice: e.target.checked })} data-testid="equipment-noprice-filter" />Prix à définir</label>
        <label className="flex h-10 items-center gap-1 text-sm"><input type="checkbox" checked={fl.noStock} onChange={(e) => setFl({ ...fl, noStock: e.target.checked })} data-testid="equipment-nostock-filter" />Sans stock</label>
        <label className="flex h-10 items-center gap-1 text-sm"><input type="checkbox" checked={!!fl.todo} onChange={(e) => setFl({ ...fl, todo: e.target.checked })} data-testid="equipment-tocomplete-filter" />À compléter</label>
        <select className={fsel} value={fl.attr} onChange={(e) => setFl({ ...fl, attr: e.target.value })} data-testid="equipment-attr-filter"><option value="">Caractéristique…</option>{attrFields.map((x) => <option key={x.code} value={x.code}>{x.label}{x.type === "number" ? " ≥" : ""}</option>)}</select>
        {fl.attr && <Input className="w-28 bg-card" placeholder="valeur" value={fl.attrVal} onChange={(e) => setFl({ ...fl, attrVal: e.target.value })} data-testid="equipment-attr-value" />}
        {sup.allowed && <select className={fsel} value={fl.sup || ""} onChange={(e) => setFl({ ...fl, sup: e.target.value })} data-testid="equipment-supplier-filter"><option value="">Tous fournisseurs</option>{[...new Map(sup.rows.map((m) => [m.supplier_id, m.supplier_name])).entries()].sort((a, b) => a[1].localeCompare(b[1])).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>}
        {write && <button className="text-sm underline" onClick={() => setKitOpen(true)} data-testid="kits-open">Nomenclatures</button>}
        {write && <button className="text-sm underline" onClick={() => setTplOpen(true)} data-testid="templates-open">Modèles de caractéristiques</button>}
        <span className="text-xs text-muted-foreground" data-testid="equipment-count">{items.length} produit(s)</span>
        {me?.user?.role === "admin" && <Link to="/import-catalogue" className="text-sm underline" data-testid="catalogue-import-link">Importer le catalogue</Link>}
        {write && <Button className="ml-auto" onClick={() => setEdit({})} data-testid="new-equipment-button"><Plus className="mr-1.5 h-4 w-4" />Matériel</Button>}
      </div>
      {!data ? <Loading /> : (
        <div className="card-soft overflow-x-auto" data-testid="equipment-table">
          <div className="p-2 empty:hidden"><BulkDelete kind="product" picked={pick} onDone={() => { setPick([]); load(); }} /></div>
          <Table>
            <TableHeader><TableRow><TableHead>Référence</TableHead><TableHead>Désignation</TableHead><TableHead>Stock</TableHead><TableHead>Réservé</TableHead><TableHead>Maint.</TableHead><TableHead>Disponibilité</TableHead><TableHead>Prix/jour</TableHead>{sup.allowed && <TableHead>Fournisseurs</TableHead>}{finance && <TableHead>Valeur rempl.</TableHead>}<TableHead /></TableRow></TableHeader>
            <TableBody>
              {items.map((i) => {
                const I = CAT_ICON[i.category] || Box;
                return (
                  <TableRow key={i.id} data-testid={`equipment-row-${i.ref}`}>
                    <TableCell><div className="flex items-center gap-2.5"><Pick id={i.id} pick={pick} setPick={setPick} />{i.photo ? <FileImg src={i.photo} className="h-9 w-9 rounded-lg object-cover" /> : <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-accent-foreground"><I className="h-4 w-4" /></span>}<span className="font-mono text-xs">{i.ref}</span></div></TableCell>
                    <TableCell><div className="font-medium">{i.name}</div><div className="text-xs text-muted-foreground">{i.category}{i.subcategory ? ` › ${i.subcategory}` : ""} · {i.product_type || "Location"}{i.provenance ? ` · ${i.provenance}` : ""}{i.to_check ? ` · à vérifier : ${i.to_check}` : ""}{i.to_complete && <span className="ml-2 rounded-full bg-amber-500/10 px-2 py-0.5 font-semibold text-amber-700" data-testid={`to-complete-${i.ref}`}>À compléter</span>}</div></TableCell>
                    <TableCell><button className="font-semibold underline" title="Stock par entrepôt" onClick={() => setStockOf(i)} data-testid={`product-stock-${i.ref}`}>{dual(i, i.qty_total)}</button></TableCell>
                    <TableCell>{i.reserved}</TableCell>
                    <TableCell>{i.qty_maintenance ? <span className="text-amber-700 font-medium">{i.qty_maintenance}</span> : 0}</TableCell>
                    <TableCell><Gauge item={i} /></TableCell>
                    <TableCell>{i.price_day == null ? <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-700" data-testid={`price-missing-${i.ref}`}>Prix à définir</span> : fmtEur(i.price_day)}</TableCell>
                    {sup.allowed && <TableCell className="text-xs" data-testid={`product-suppliers-${i.ref}`}>{sup.rows.filter((m) => m.product_id === i.id).map((m) => `${m.is_preferred ? "★ " : ""}${m.supplier_name}`).join(", ")}</TableCell>}
                    {finance && <TableCell>{fmtEur(i.replacement_value)}</TableCell>}
                    <TableCell><div className="flex justify-end gap-1">
                      {prim[i.id] && <Button size="icon" variant="ghost" title={`Ouvrir : ${prim[i.id].title}`} onClick={() => openFile(prim[i.id].file_ref)} data-testid={`product-primary-pdf-${i.ref}`}><FileDown className="h-4 w-4 text-red-600" /></Button>}
                      <Button size="sm" variant="ghost" className="gap-1 px-2" title={i.requirements?.length ? `${i.requirements.length} besoin(s) : ${i.requirements.map((r) => r.label).join(", ")}` : "Documents et besoins"} onClick={() => setSheet(i.id)} data-testid={`product-sheet-${i.ref}`}><FileText className="h-4 w-4" />{i.requirements?.length > 0 && <span className="rounded-full bg-secondary px-1.5 text-[10px] font-semibold" data-testid={`product-reqs-count-${i.ref}`}>{i.requirements.length}</span>}</Button>
                      <Button size="icon" variant="ghost" title="Réservations" onClick={() => setBook(i.id)} data-testid={`bookings-${i.ref}`}><CalendarRange className="h-4 w-4" /></Button>
                      {write && i.product_type === "Pack" && <Button size="sm" variant="outline" onClick={() => setPack(i)} data-testid={`pack-composition-${i.ref}`}>Composition ({(i.components || []).length}) · v{i.version || 1}</Button>}
                      {write && i.product_type === "Pack" && <><Button size="sm" variant="outline" onClick={() => setPtr(i)} data-testid={`pack-translations-${i.ref}`}>Traductions</Button><Button size="sm" variant="outline" onClick={() => setPapply(i)} data-testid={`pack-apply-${i.ref}`}>Appliquer aux devis</Button></>}
                      {write && <Button size="icon" variant="ghost" title="Maintenance" onClick={() => setMaint(i)} data-testid={`maintenance-${i.ref}`}><Wrench className="h-4 w-4" /></Button>}
                      {write && <Button size="icon" variant="ghost" title="Modifier" onClick={() => setEdit(i)} data-testid={`edit-equipment-${i.ref}`}><Pencil className="h-4 w-4" /></Button>}
                      <TrashBtn kind="product" id={i.id} name={i.name} onDone={load} />
                    </div></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <TemplatesDialog open={tplOpen} onOpenChange={setTplOpen} onSaved={loadTpls} />
      <KitEditor open={kitOpen} onOpenChange={setKitOpen} />
      <EquipmentDialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)} item={edit?.id ? edit : null} onSaved={load} cats={(data?.items || []).map((i) => [i.category, i.subcategory])} />
      <MaintenanceDialog item={maint} onOpenChange={(o) => !o && setMaint(null)} onSaved={load} />
      <StockDialog item={stockOf} onClose={() => setStockOf(null)} />
      <BookingsSheet id={book} onOpenChange={(o) => !o && setBook(null)} />
      {ptr && <PackTranslations item={ptr} onClose={() => setPtr(null)} />}
      {papply && <PackApply item={papply} onClose={() => setPapply(null)} />}
      {pack && <PackComposition item={pack} equipment={data?.items || []} onClose={() => setPack(null)} onSaved={load} />}
      <ProductSheetDialog item={(data?.items || []).find((x) => x.id === sheet) || null} equipment={data?.items || []} write={write} admin={can("users:manage")} onOpenChange={(o) => !o && setSheet(null)} onSaved={() => { load(); loadDocs(); }} />
    </>
  );
}

function Packs({ write }) {
  const [packs, setPacks] = useState(null);
  const [eq, setEq] = useState([]);
  const [edit, setEdit] = useState(null);
  const load = () => api.get("/packs").then((r) => setPacks(r.data));
  useEffect(() => { load(); api.get("/equipment").then((r) => setEq(r.data.items)); }, []);
  const name = (id) => eq.find((e) => e.id === id);
  if (!packs) return <Loading />;
  return (
    <>
      {write && <div className="mb-4 flex justify-end"><Button onClick={() => setEdit({})} data-testid="new-pack-button"><Plus className="mr-1.5 h-4 w-4" />Pack</Button></div>}
      {!packs.length ? <EmptyState title="Aucun pack" /> : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {packs.map((p) => (
            <div key={p.id} className="card-soft p-5 hover-lift" data-testid={`pack-card-${p.id}`}>
              <div className="flex items-start justify-between gap-2"><ModuleBadge module={p.module} />{!p.active && <span className="text-xs text-muted-foreground">Inactif</span>}<TrashBtn kind="pack" id={p.id} name={p.name} onDone={load} /></div>
              <div className="mt-2 font-display text-xl">{p.name}</div>
              <p className="mt-1 text-sm text-muted-foreground">{p.description}</p>
              <div className="mt-3 font-display text-2xl text-primary">{fmtEur(p.price)} <span className="text-xs font-sans text-muted-foreground">HT</span></div>
              <ul className="mt-3 space-y-1 text-xs">{p.items.map((it) => <li key={it.equipment_id}>{it.qty} × {name(it.equipment_id)?.name || "…"}</li>)}</ul>
              {p.services.length > 0 && <div className="mt-2 text-xs text-muted-foreground">Inclus : {p.services.join(", ")}</div>}
              {p.options.length > 0 && <div className="mt-1 text-xs text-muted-foreground">Options : {p.options.join(", ")}</div>}
              {write && <Button variant="outline" size="sm" className="mt-4" onClick={() => setEdit(p)} data-testid={`edit-pack-${p.id}`}>Modifier</Button>}
            </div>
          ))}
        </div>
      )}
      <PackDialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)} pack={edit?.id ? edit : null} equipment={eq} onSaved={load} />
    </>
  );
}

function Maintenance() {
  const [items, setItems] = useState(null);
  useEffect(() => { api.get("/equipment").then((r) => setItems(r.data.items)); }, []);
  if (!items) return <Loading />;
  const inM = items.filter((i) => i.qty_maintenance > 0);
  const logs = items.flatMap((i) => (i.maintenance_log || []).map((m) => ({ ...m, item: i }))).sort((a, b) => b.at.localeCompare(a.at));
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2" data-testid="maintenance-tab">
      <div className="card-soft p-5"><h3 className="mb-3 font-semibold">En maintenance</h3>
        {!inM.length ? <div className="text-sm text-muted-foreground">Aucun matériel en maintenance.</div> : inM.map((i) => <div key={i.id} className="flex justify-between border-b border-border py-2 text-sm last:border-0"><span>{i.ref} · {i.name}</span><span className="font-semibold text-amber-700">{i.qty_maintenance} / {i.qty_total}</span></div>)}</div>
      <div className="card-soft p-5"><h3 className="mb-3 font-semibold">Journal</h3>
        {logs.map((m) => <div key={m.id} className="border-b border-border py-2 text-xs last:border-0"><b>{m.item.name}</b> — {m.action === "start" ? "mise en maintenance" : "remise en service"} ×{m.qty} · {m.note} <span className="text-muted-foreground">({m.by}, {new Date(m.at).toLocaleDateString("fr-FR")})</span></div>)}</div>
    </div>
  );
}

export default function Catalogue() {
  const { can } = useMe();
  const [params] = useSearchParams();
  const write = can("catalog:write");
  return (
    <div>
      <PageHeader eyebrow="Opérations · Loueur de matériel" title="Catalogue & matériel" subtitle="Stock, disponibilités calculées par période (sortie → retour), packs commercialisables et maintenance." />
      <Tabs defaultValue={params.get("tab") || "stock"}>
        <TabsList className="mb-5"><TabsTrigger value="stock" data-testid="catalogue-tab-stock">Matériel</TabsTrigger><TabsTrigger value="packs" data-testid="catalogue-tab-packs">Packs & produits</TabsTrigger><TabsTrigger value="maintenance" data-testid="catalogue-tab-maintenance">Maintenance</TabsTrigger></TabsList>
        <TabsContent value="stock"><Inventory write={write} finance={can("finance:read")} /></TabsContent>
        <TabsContent value="packs"><Packs write={write} /></TabsContent>
        <TabsContent value="maintenance"><Maintenance /></TabsContent>
      </Tabs>
    </div>
  );
}
