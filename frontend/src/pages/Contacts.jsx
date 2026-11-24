import { useCallback, useEffect, useMemo, useState } from "react";
import { TrashBtn, Pick, BulkDelete } from "@/components/Trash";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Search, Phone, Mail, MessageSquare, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PageHeader, Loading, Field, StatusBadge, Info } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { LanguageSelect, langLabel } from "@/lib/i18n";
import { fmtDate, fmtEur } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { Pill, WpBadge, StatusesDialog, statusKeys } from "@/components/contacts/Statuses";
import { SupplierProducts } from "@/components/catalogue/Suppliers";
import { PeopleBlock, CategoriesField } from "@/components/contacts/People";
import { ProviderDialog } from "@/components/providers/ProviderDialog";

const EMPTY = { kind: "particulier", status: "prospect", first_name: "", last_name: "", company: "", email: "", phone: "", address: "", city: "", source: "", tags: [], notes: "", types: ["client"], statuses: {}, language: "fr-FR" };
const C_TYPES = { client: "Client", prestataire: "Prestataire", lieu: "Lieu", fournisseur: "Fournisseur", autre: "Autre" };
const IT_TYPES = { appel: "Appel", email: "E-mail", rdv: "Rendez-vous", note: "Note" };

function ContactDialog({ open, onOpenChange, contact, onSaved, meta, preset }) {
  const [f, setF] = useState(EMPTY);
  useEffect(() => { if (open) setF(contact ? Object.fromEntries(Object.keys(EMPTY).map((k) => [k, contact[k] ?? EMPTY[k]])) : { ...EMPTY, ...preset }); }, [open, contact]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k) => (e) => setF({ ...f, [k]: e?.target ? e.target.value : e });
  const submit = async (e) => {
    e.preventDefault();
    try { contact ? await api.put(`/contacts/${contact.id}`, f) : await api.post("/contacts", f); toast.success("Contact enregistré"); onSaved(); onOpenChange(false); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{contact ? "Modifier le contact" : "Nouveau contact"}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-4" data-testid="contact-form">
          <Field label="Type"><Select value={f.kind} onValueChange={set("kind")}><SelectTrigger data-testid="contact-kind-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="particulier">Particulier</SelectItem><SelectItem value="entreprise">Entreprise</SelectItem></SelectContent></Select></Field>
          <div />
          {f.kind === "entreprise" && <Field label="Société" className="col-span-2"><Input value={f.company} onChange={set("company")} data-testid="contact-company-input" /></Field>}
          <Field label="Type de contact" className="col-span-2"><div className="flex flex-wrap gap-2" data-testid="contact-types">{Object.entries(C_TYPES).map(([k, l]) => { const on = f.types.includes(k); return <button key={k} type="button" aria-pressed={on} onClick={() => setF({ ...f, types: on ? f.types.filter((x) => x !== k) : [...f.types, k] })} data-testid={`contact-type-${k}`} className={`h-8 rounded-full border px-3.5 text-xs font-medium ${on ? "border-primary bg-primary text-white" : "border-border"}`}>{l}</button>; })}</div></Field>
          {meta && statusKeys(f.types, contact?.is_wedding_planner).map((k) => { const v = f.statuses[k] || (k === "client" && f.status) || meta.defaults[k]; return (
            <Field key={k} label={`Statut — ${meta.labels[k]}`}><select className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm" value={v} onChange={(e) => setF({ ...f, statuses: { ...f.statuses, [k]: e.target.value }, status: k === "client" ? e.target.value : f.status })} data-testid={`contact-status-${k}`}>
              {meta.lists[k].map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select></Field>); })}
          {contact?.id && f.types.includes("prestataire") && <CategoriesField contact={contact} onSaved={onSaved} />}
          <div className="col-span-2 -mt-2" />
          <Field label="Prénom"><Input value={f.first_name} onChange={set("first_name")} data-testid="contact-firstname-input" /></Field>
          <Field label="Nom"><Input value={f.last_name} onChange={set("last_name")} data-testid="contact-lastname-input" /></Field>
          <Field label="E-mail"><Input type="email" value={f.email} onChange={set("email")} data-testid="contact-email-input" /></Field>
          <Field label="Téléphone"><Input value={f.phone} onChange={set("phone")} data-testid="contact-phone-input" /></Field>
          <Field label="Adresse"><Input value={f.address} onChange={set("address")} /></Field>
          <Field label="Ville"><Input value={f.city} onChange={set("city")} data-testid="contact-city-input" /></Field>
          <Field label="Instagram" className="col-span-2"><Input value={f.instagram_handle || ""} onChange={set("instagram_handle")} placeholder="identifiant sans @" data-testid="contact-instagram-input" /></Field>
          <Field label="Source" className="col-span-2"><Input value={f.source} onChange={set("source")} placeholder="Salon, Instagram, recommandation…" /></Field>
          <Field label="Langue de communication" className="col-span-2"><LanguageSelect value={f.language} onChange={set("language")} testid="contact-language-select" /></Field>
          <Field label="Notes" className="col-span-2"><Textarea rows={2} value={f.notes} onChange={set("notes")} /></Field>
          <DialogFooter className="col-span-2"><Button disabled={!(f.first_name || f.last_name || f.company)} data-testid="contact-form-submit">Enregistrer</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ContactSheet({ id, onOpenChange, onEdit, write }) {
  const [c, setC] = useState(null);
  const [it, setIt] = useState({ type: "appel", note: "" });
  const load = useCallback(() => { if (id) api.get(`/contacts/${id}`).then((r) => setC(r.data)); }, [id]);
  useEffect(() => { setC(null); load(); }, [load]);
  const add = async () => {
    try { await api.post(`/contacts/${id}/interactions`, it); setIt({ type: "appel", note: "" }); load(); toast.success("Échange ajouté"); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Sheet open={!!id} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader><SheetTitle className="font-display text-2xl font-medium">{c?.display_name || "…"}</SheetTitle></SheetHeader>
        {c && (
          <div className="mt-4 space-y-6" data-testid="contact-sheet">
            <div className="flex flex-wrap items-center gap-2">{c.is_wedding_planner && <WpBadge testid="contact-sheet-wp-badge" />}{c.status_badges.map((b) => <Pill key={b.type} color={b.color} title={b.type_label} testid={`contact-sheet-status-${b.type}`}>{b.label}</Pill>)}<span className="text-xs text-muted-foreground capitalize">{c.kind}</span>{(c.types || []).map((t) => <span key={t} className="rounded-full border border-border px-2.5 py-0.5 text-xs" data-testid={`contact-sheet-type-${t}`}>{C_TYPES[t]}</span>)}
              {write && <Button size="sm" variant="outline" className="ml-auto" onClick={() => onEdit(c)} data-testid="edit-contact-button"><Pencil className="mr-1 h-3.5 w-3.5" />Modifier</Button>}{write && <Link to={`/devis-factures?new=1&client=${c.id}`} className="text-sm font-semibold underline" data-testid="contact-new-quote">+ Devis</Link>}</div>
            <div className="grid grid-cols-2 gap-4"><Info label="E-mail" value={c.email} /><Info label="Téléphone" value={c.phone} /><Info label="Ville" value={c.city} /><Info label="Source" value={c.source} /><Info label="Langue" value={langLabel(c.language)} /></div>
            {c.is_wedding_planner && c.provider_id && <Link to={`/prestataires?id=${c.provider_id}&ptab=events`} className="block rounded-lg bg-pink-500/10 p-3 text-sm font-medium text-pink-700 underline" data-testid="contact-planner-events">Événements apportés : {c.planner_events.upcoming} à venir · {c.planner_events.past} passés</Link>}
            {!c.is_wedding_planner && c.categories.length > 0 && <div className="flex flex-wrap gap-1.5">{c.categories.map((k) => <span key={k.key} className="rounded-full border border-border px-2 py-0.5 text-xs">{k.label}</span>)}</div>}
            {c.notes && <p className="rounded-lg bg-secondary p-3 text-sm">{c.notes}</p>}
            {c.types.some((t) => ["prestataire", "fournisseur", "lieu"].includes(t)) && <PeopleBlock contactId={c.id} write={write} />}
            {c.types.includes("fournisseur") && <SupplierProducts contactId={c.id} write={write} />}
            <div><div className="eyebrow mb-2">Événements ({c.events.length})</div>
              {c.events.map((e) => <Link key={e.id} to={`/evenements/${e.id}`} className="flex items-center justify-between rounded-lg px-2 py-2 hover:bg-secondary"><div><div className="text-sm font-medium">{e.title}</div><div className="text-xs text-muted-foreground">{e.code} · {fmtDate(e.start)}</div></div><div className="flex items-center gap-2">{e.amount_ht != null && <span className="text-xs">{fmtEur(e.amount_ht)}</span>}<StatusBadge status={e.status} /></div></Link>)}</div>
            <div><div className="eyebrow mb-2">Historique des échanges</div>
              {write && (
                <div className="mb-3 flex gap-2">
                  <Select value={it.type} onValueChange={(v) => setIt({ ...it, type: v })}><SelectTrigger className="w-36"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(IT_TYPES).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent></Select>
                  <Input placeholder="Résumé de l'échange…" value={it.note} onChange={(e) => setIt({ ...it, note: e.target.value })} data-testid="interaction-note-input" />
                  <Button onClick={add} disabled={!it.note} data-testid="add-interaction-button">Ajouter</Button>
                </div>
              )}
              {[...(c.interactions || [])].reverse().map((x) => <div key={x.id} className="flex gap-3 border-b border-border py-2.5 last:border-0"><MessageSquare className="mt-0.5 h-4 w-4 text-primary" /><div><div className="text-sm">{x.note}</div><div className="text-xs text-muted-foreground">{IT_TYPES[x.type]} · {x.by} · {new Date(x.at).toLocaleDateString("fr-FR")}</div></div></div>)}
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

const CHIPS = [["all", "Tous"], ["client", "Clients"], ["wp", "Wedding planners"], ["prestataire", "Prestataires"], ["lieu", "Lieux"], ["fournisseur", "Fournisseurs"], ["autre", "Autres"]];
const inChip = (c, k, noWp) => k === "all" || (k === "wp" ? c.is_wedding_planner : k === "prestataire" ? c.types.includes(k) && !(noWp && c.is_wedding_planner) : c.types.includes(k));
const role = (c) => (c.is_wedding_planner ? "Wedding planner" : c.categories.map((k) => k.label).join(", "));

export default function Contacts() {
  const { can } = useMe();
  const write = can("contacts:write");
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState(null);
  const [meta, setMeta] = useState(null);
  const [cats, setCats] = useState([]);
  const [q, setQ] = useState("");
  const [chip, setChip] = useState("all");
  const [noWp, setNoWp] = useState(false);
  const [status, setStatus] = useState("");
  const [jobs, setJobs] = useState([]);
  const [sort, setSort] = useState(0);
  const [edit, setEdit] = useState(null);
  const [menu, setMenu] = useState(false);
  const [dlg, setDlg] = useState(null);
  const [pick, setPick] = useState([]);
  const load = useCallback(() => api.get("/contacts", { params: { q: q || undefined } }).then((r) => setRows(r.data)), [q]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);
  useEffect(() => { api.get("/contact-statuses").then((r) => setMeta(r.data)).catch(() => {}); if (can("providers:manage")) api.get("/provider-categories").then((r) => setCats(r.data)).catch(() => {}); }, [can]);
  const openId = params.get("id");
  const sKey = { client: "client", wp: "wedding_planner", prestataire: "prestataire", lieu: "lieu", fournisseur: "fournisseur" }[chip];
  const allJobs = useMemo(() => Object.values(Object.fromEntries((rows || []).flatMap((c) => c.categories).map((k) => [k.key, k]))).sort((a, b) => a.label.localeCompare(b.label)), [rows]);
  const shown = useMemo(() => {
    const out = (rows || []).filter((c) => inChip(c, chip, noWp) && (!status || Object.values(c.statuses).includes(status)) && (!jobs.length || c.categories.some((k) => jobs.includes(k.key))));
    return sort ? [...out].sort((a, b) => sort * role(a).localeCompare(role(b))) : out;
  }, [rows, chip, noWp, status, jobs, sort]);
  return (
    <div>
      <PageHeader eyebrow="Administratif" title="Contacts" subtitle="Clients, wedding planners, prestataires, lieux et fournisseurs."
        actions={<>{can("org:write") && <Button variant="outline" size="sm" onClick={() => setDlg("statuses")} data-testid="contact-statuses-button">Statuts</Button>}
          {write && <div className="relative"><Button onClick={() => setMenu(!menu)} data-testid="new-contact-button"><Plus className="mr-1.5 h-4 w-4" />Nouveau contact</Button>
            {menu && <div className="absolute right-0 z-20 mt-1 w-52 rounded-xl border border-border bg-card p-1 shadow-lg" data-testid="new-contact-menu">
              {[["client", "Client"], ["wp", "Wedding planner"], ["prestataire", "Prestataire"], ["lieu", "Lieu"], ["fournisseur", "Fournisseur"], ["autre", "Autre"]].map(([k, l]) => <button key={k} className="block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-secondary" data-testid={`new-contact-${k}`}
                onClick={() => { setMenu(false); k === "wp" ? setDlg("wp") : setEdit({ types: [k] }); }}>{l}</button>)}</div>}</div>}</>} />
      <div className="mb-3 flex flex-wrap gap-1.5" data-testid="contacts-chips">
        {CHIPS.map(([k, l]) => <button key={k} onClick={() => { setChip(k); setStatus(""); }} data-testid={`contacts-chip-${k}`} className={`h-9 rounded-full border px-4 text-sm font-medium ${chip === k ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`}>{l} <span className="opacity-70" data-testid={`contacts-chip-count-${k}`}>{(rows || []).filter((c) => inChip(c, k, k === chip && noWp)).length}</span></button>)}
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input className="bg-card pl-9" placeholder="Nom, société, métier, e-mail, ville…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="contacts-search-input" /></div>
        {chip === "prestataire" && <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={noWp} onChange={(e) => setNoWp(e.target.checked)} data-testid="contacts-exclude-wp" />Exclure les wedding planners</label>}
        {meta && sKey && <select className="h-10 rounded-lg border border-border bg-card px-3 text-sm" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="contacts-status-filter"><option value="">Tous les statuts</option>{meta.lists[sKey].map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select>}
        {allJobs.length > 0 && <div className="flex flex-wrap items-center gap-1" data-testid="contacts-job-filter"><span className="text-xs text-muted-foreground">Métiers :</span>{allJobs.map((k) => { const on = jobs.includes(k.key); return <button key={k.key} aria-pressed={on} onClick={() => setJobs(on ? jobs.filter((x) => x !== k.key) : [...jobs, k.key])} data-testid={`contacts-job-${k.key}`} className={`h-7 rounded-full border px-2.5 text-xs ${on ? "border-primary bg-primary text-white" : "border-border"}`}>{k.label}</button>; })}</div>}
      </div>
      {!rows ? <Loading /> : (
        <div className="card-soft overflow-x-auto" data-testid="contacts-table">
          <div className="p-2 empty:hidden"><BulkDelete kind="contact" picked={pick} onDone={() => { setPick([]); load(); }} /></div><Table>
            <TableHeader><TableRow><TableHead>Nom</TableHead><TableHead><button className="underline-offset-2 hover:underline" onClick={() => setSort(sort === 1 ? -1 : 1)} data-testid="contacts-sort-role">Rôle / métier {sort === 1 ? "↑" : sort === -1 ? "↓" : ""}</button></TableHead><TableHead>Coordonnées</TableHead><TableHead>Ville</TableHead><TableHead>Statut</TableHead><TableHead>Événements</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {shown.map((c) => (
                <TableRow key={c.id} className="cursor-pointer" onClick={() => setParams({ id: c.id })} data-testid={`contact-row-${c.id}`}>
                  <TableCell><div className="flex flex-wrap items-center gap-1.5 font-medium"><Pick id={c.id} pick={pick} setPick={setPick} />{c.display_name}{c.is_wedding_planner && <WpBadge testid={`contact-wp-badge-${c.id}`} />}</div>{(c.matched_people || []).map((m) => <div key={m} className="text-xs font-medium text-primary" data-testid={`contact-matched-person-${c.id}`}>{m}</div>)}<div className="text-xs text-muted-foreground">{c.kind === "entreprise" ? `${c.first_name} ${c.last_name}` : "Particulier"} · {(c.types || []).map((t) => C_TYPES[t]).join(", ")}</div></TableCell>
                  <TableCell data-testid={`contact-role-${c.id}`}><div className="flex flex-wrap gap-1">{c.categories.filter((k) => k.key !== "wedding_planner").map((k) => <span key={k.key} className="rounded-full border border-border px-2 py-0.5 text-xs">{k.label}</span>)}{c.is_wedding_planner && !c.categories.some((k) => k.key !== "wedding_planner") && <span className="text-xs text-muted-foreground">Wedding planner</span>}</div></TableCell>
                  <TableCell className="text-xs"><div className="flex items-center gap-1.5"><Mail className="h-3 w-3" />{c.email || "—"}</div><div className="flex items-center gap-1.5"><Phone className="h-3 w-3" />{c.phone || "—"}</div></TableCell>
                  <TableCell>{c.city}</TableCell>
                  <TableCell><div className="flex flex-wrap gap-1" data-testid={`contact-status-cell-${c.id}`}>{c.status_badges.filter((b) => !sKey || b.type === sKey).map((b) => <Pill key={b.type} color={b.color} title={b.type_label}>{b.label}</Pill>)}</div></TableCell>
                  <TableCell>{c.events_count}</TableCell><TableCell><TrashBtn kind="contact" id={c.id} name={c.display_name} onDone={load} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <ContactDialog meta={meta} open={!!edit} onOpenChange={(o) => !o && setEdit(null)} contact={edit?.id ? edit : null} preset={edit && !edit.id ? edit : null} onSaved={load} />
      <ContactSheet id={openId} write={write} onOpenChange={(o) => !o && setParams({})} onEdit={(c) => { setParams({}); setEdit(c); }} />
      <StatusesDialog open={dlg === "statuses"} onOpenChange={(o) => setDlg(o ? "statuses" : null)} meta={meta} onSaved={(m) => { setMeta(m); load(); }} />
      <ProviderDialog open={dlg === "wp"} onOpenChange={(o) => setDlg(o ? "wp" : null)} provider={null} categories={cats} preset={{ categories: ["wedding_planner"] }} onSaved={load} onOpenExisting={() => {}} />
    </div>
  );
}
