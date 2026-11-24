import { useCallback, useEffect, useRef, useState } from "react";
import { PurchaseLines } from "@/components/catalogue/Suppliers";
import { toast } from "sonner";
import { Plus, Download, Pencil, Trash2, Paperclip, Upload, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { PageHeader, Loading, Field, EmptyState } from "@/components/common";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { openFile } from "@/lib/files";
import { fmtDate, fmtEur2, dayKey } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { TrashDialog } from "@/components/Trash";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm";
const th = "px-4 py-3 text-left text-xs font-semibold text-muted-foreground";
const td = "px-4 py-3 align-top";
const CATS = { carburant: "Carburant", peage: "Péage", repas: "Repas", hebergement: "Hébergement", parking: "Parking", autre: "Autre" };
const X_STATUS = { soumise: "Soumise", validee: "Validée", remboursee: "Remboursée" };
const PERIOD = { monthly: "Mensuel", quarterly: "Trimestriel", yearly: "Annuel" };
const Pill = ({ tone = "", children, testid }) => <span data-testid={testid} className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${tone || "bg-secondary"}`}>{children}</span>;

function useList(path, params) {
  const [d, setD] = useState(null);
  const key = JSON.stringify(params || {});
  const load = useCallback(() => api.get(path, { params: JSON.parse(key) }).then((r) => setD(r.data)).catch(ko), [path, key]);
  useEffect(() => { load(); }, [load]);
  return [d, load];
}

function useOptions(path) {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get(path).then((r) => setRows(r.data)).catch(() => {}); }, [path]);
  return rows;
}

async function extract(file, kind) {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await api.post(`/documents/extract?kind=${kind}`, fd);
  if (data.message) toast.info(data.message); else toast.success("Montants extraits : vérifiez avant d'enregistrer");
  return data;
}

function FormDialog({ title, value, fields, onClose, onSubmit, testid, children }) {
  const [f, setF] = useState(value || {});
  useEffect(() => { if (value) setF(value); }, [value]);
  const num = (x) => (x.type === "number" ? Number(f[x.k]) || 0 : f[x.k]);
  return (
    <Dialog open={!!value} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{title}</DialogTitle></DialogHeader>
        <form onSubmit={(e) => { e.preventDefault(); onSubmit({ ...f, ...Object.fromEntries(fields.map((x) => [x.k, num(x)])) }); }} className="grid grid-cols-2 gap-4" data-testid={`${testid}-form`}>
          {children?.(f, setF)}
          {fields.map((x) => (
            <Field key={x.k} label={x.label} className={x.wide ? "col-span-2" : ""}>
              {x.options ? <select className={sel} value={f[x.k] ?? ""} onChange={(e) => setF({ ...f, [x.k]: e.target.value })} data-testid={`${testid}-${x.k}`}>{x.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                : x.type === "checkbox" ? <input type="checkbox" className="h-5 w-5" checked={!!f[x.k]} onChange={(e) => setF({ ...f, [x.k]: e.target.checked })} data-testid={`${testid}-${x.k}`} />
                  : <Input type={x.type || "text"} step={x.type === "number" ? "0.01" : undefined} min={x.type === "number" ? "0" : undefined} required={x.required} value={f[x.k] ?? ""} onChange={(e) => setF({ ...f, [x.k]: e.target.value })} data-testid={`${testid}-${x.k}`} />}
            </Field>
          ))}
          <DialogFooter className="col-span-2"><Button data-testid={`${testid}-submit`}>Enregistrer</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const save = (path, f, load, close) => (f.id ? api.put(`${path}/${f.id}`, f) : api.post(path, f)).then(() => { toast.success("Enregistré"); load(); close(); }).catch(ko);
const del = (path, id, load) => window.confirm("Placer cet élément dans la Corbeille (30 jours) ?") && api.delete(`${path}/${id}`).then(load).catch(ko);
const evOpts = (events) => [["", "Aucun"], ...events.map((e) => [e.id, `${e.code} · ${e.title}`])];

function FilePick({ f, setF, kind, field, map }) {
  const ref = useRef(null);
  const [busy, setBusy] = useState(false);
  const pick = async (e) => { const file = e.target.files[0]; e.target.value = ""; if (!file) return; setBusy(true); try { const r = await extract(file, kind); setF((cur) => ({ ...cur, ...map(r.extracted || {}), [field]: r.file_id })); } catch (err) { ko(err); } setBusy(false); };
  return (
    <div className="col-span-2 flex flex-wrap items-center gap-3 rounded-xl border border-dashed border-border p-3">
      <input ref={ref} type="file" hidden accept="image/*,application/pdf" capture={kind === "receipt" ? "environment" : undefined} onChange={pick} data-testid={`${kind}-file-input`} />
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => ref.current.click()} data-testid={`${kind}-file-button`}><Upload />{busy ? "Lecture…" : kind === "receipt" ? "Photo du justificatif" : "Joindre le PDF"}</Button>
      {f[field] ? <button type="button" className="flex items-center gap-1 text-sm underline" onClick={() => openFile(`file:${f[field]}`)}><Paperclip className="h-3.5 w-3.5" />Voir le fichier</button> : <span className="text-xs text-muted-foreground">Les montants sont lus automatiquement quand l'assistant IA est configuré.</span>}
    </div>
  );
}
const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v !== 0 && v != null));

export function Expenses() {
  const { can } = useMe();
  const [month, setMonth] = useState(dayKey(new Date()).slice(0, 7));
  const [d, load] = useList("/expenses", { month });
  const events = useOptions("/events");
  const vehicles = useOptions("/vehicles");
  const [edit, setEdit] = useState(null);
  if (!d) return <Loading />;
  const fw = can("finance:write");
  const fields = [{ k: "date", label: "Date", type: "date", required: true }, { k: "category", label: "Catégorie", options: Object.entries(CATS) }, { k: "amount_ttc", label: "Montant TTC (€)", type: "number", required: true }, { k: "vat", label: "Dont TVA (€)", type: "number" },
    ...(fw ? [{ k: "user_id", label: "Personne", options: d.people.map((p) => [p.id, p.name]) }] : []), { k: "event_id", label: "Événement lié", options: evOpts(events) }, { k: "vehicle_id", label: "Véhicule lié", options: [["", "Aucun"], ...vehicles.map((v) => [v.id, v.name])] }, { k: "note", label: "Note", wide: !fw }];
  return (
    <div data-testid="expenses-page">
      <PageHeader title="Notes de frais" subtitle="Saisissez un frais avec la photo du justificatif ; la comptabilité valide puis rembourse."
        actions={<><Input type="month" className="w-44" value={month} onChange={(e) => setMonth(e.target.value)} data-testid="expenses-month" />
          <Button variant="outline" onClick={() => downloadPdf(`/expenses?month=${month}&format=csv`, `notes-de-frais-${month}.csv`).catch(ko)} data-testid="expenses-export"><Download />Export CSV</Button>
          <Button onClick={() => setEdit({ date: dayKey(new Date()), user_id: d.me, category: "carburant", amount_ttc: "", vat: "", event_id: "", vehicle_id: "", receipt_file_id: "", note: "" })} data-testid="new-expense-button"><Plus />Note de frais</Button></>} />
      {!d.rows.length ? <EmptyState title="Aucune note de frais ce mois-ci" text="Ajoutez un frais : carburant, péage, repas, hébergement, parking." /> : (
        <div className="card-soft overflow-x-auto"><table className="w-full min-w-[820px] text-sm" data-testid="expenses-table">
          <thead><tr className="border-b border-border"><th className={th}>Date</th><th className={th}>Personne</th><th className={th}>Catégorie</th><th className={th}>TTC</th><th className={th}>TVA</th><th className={th}>Lié à</th><th className={th}>Statut</th><th className={th} /></tr></thead>
          <tbody>{d.rows.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-0" data-testid={`expense-row-${r.id}`}>
              <td className={td}>{fmtDate(r.date)}</td><td className={td}>{r.user_name}</td><td className={td}>{CATS[r.category]}{r.note && <div className="text-xs text-muted-foreground">{r.note}</div>}</td>
              <td className={`${td} font-semibold`}>{fmtEur2(r.amount_ttc)}</td><td className={td}>{fmtEur2(r.vat)}</td><td className={td}>{[r.event_title, r.vehicle_name].filter(Boolean).join(" · ") || "—"}</td>
              <td className={td}>{fw ? <select className="h-8 rounded-lg border border-border bg-background px-2 text-xs" value={r.status} onChange={(e) => api.post(`/expenses/${r.id}/status`, { status: e.target.value }).then(load).catch(ko)} data-testid={`expense-status-${r.id}`}>{Object.entries(X_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select> : <Pill testid={`expense-status-${r.id}`}>{X_STATUS[r.status]}</Pill>}</td>
              <td className={`${td} whitespace-nowrap text-right`}>{r.receipt_file_id && <button className="icon-btn" onClick={() => openFile(`file:${r.receipt_file_id}`)} aria-label="Justificatif"><Paperclip className="h-4 w-4" /></button>}
                {(fw || (r.user_id === d.me && r.status === "soumise")) && <><button className="icon-btn" onClick={() => setEdit(r)} aria-label="Modifier" data-testid={`expense-edit-${r.id}`}><Pencil className="h-4 w-4" /></button><button className="icon-btn" onClick={() => del("/expenses", r.id, load)} aria-label="Supprimer" data-testid={`expense-delete-${r.id}`}><Trash2 className="h-4 w-4" /></button></>}</td>
            </tr>))}</tbody>
          <tfoot><tr><td className={td} colSpan={3}>Total du mois</td><td className={`${td} font-semibold`} data-testid="expenses-total">{fmtEur2(d.total_ttc)}</td><td colSpan={4} /></tr></tfoot></table></div>)}
      <FormDialog testid="expense" title={edit?.id ? "Modifier la note de frais" : "Nouvelle note de frais"} value={edit} fields={fields} onClose={() => setEdit(null)} onSubmit={(f) => save("/expenses", f, load, () => setEdit(null))}>
        {(f, setF) => <FilePick f={f} setF={setF} kind="receipt" field="receipt_file_id" map={(x) => clean({ date: x.date, category: CATS[x.category] ? x.category : "", amount_ttc: x.amount_ttc, vat: x.vat })} />}
      </FormDialog>
    </div>
  );
}

export function Purchases() {
  const { can } = useMe();
  const [d, load] = useList("/purchase-invoices");
  const events = useOptions("/events");
  const suppliers = useOptions("/contacts?type=fournisseur");
  const [edit, setEdit] = useState(null);
  const [over, setOver] = useState(false);
  if (!d) return <Loading />;
  const fw = can("finance:write");
  const blank = { supplier_contact_id: "", supplier_name: "", number: "", date: dayKey(new Date()), due_date: "", amount_ht: "", vat: "", amount_ttc: "", category: "", event_id: "", file_id: "", status: "a_payer" };
  const map = (x) => clean({ supplier_name: x.supplier_name, number: x.number, date: x.date, due_date: x.due_date, amount_ht: x.amount_ht, vat: x.vat, amount_ttc: x.amount_ttc, category: x.category });
  const drop = async (e) => { e.preventDefault(); setOver(false); const file = e.dataTransfer.files[0]; if (!file || !fw) return; try { const r = await extract(file, "invoice"); setEdit({ ...blank, ...map(r.extracted || {}), file_id: r.file_id }); } catch (err) { ko(err); } };
  const fields = [{ k: "supplier_contact_id", label: "Fournisseur (contact)", options: [["", "Saisie libre"], ...suppliers.map((c) => [c.id, c.company || [c.first_name, c.last_name].filter(Boolean).join(" ")])] }, { k: "supplier_name", label: "Nom du fournisseur" }, { k: "number", label: "N° de facture" }, { k: "category", label: "Catégorie" },
    { k: "date", label: "Date", type: "date", required: true }, { k: "due_date", label: "Échéance", type: "date" }, { k: "amount_ht", label: "HT (€)", type: "number" }, { k: "vat", label: "TVA (€)", type: "number" }, { k: "amount_ttc", label: "TTC (€)", type: "number" },
    { k: "status", label: "Statut", options: [["a_payer", "À payer"], ["payee", "Payée"]] }, { k: "event_id", label: "Événement lié", options: evOpts(events), wide: true }];
  return (
    <div data-testid="purchases-page" onDragOver={(e) => { if (fw) { e.preventDefault(); setOver(true); } }} onDragLeave={() => setOver(false)} onDrop={drop}>
      <PageHeader title="Factures d'achat" subtitle={`${d.to_pay_count} facture(s) à payer, soit ${fmtEur2(d.to_pay_total)}.`}
        actions={fw && <Button onClick={() => setEdit(blank)} data-testid="new-purchase-button"><Plus />Facture d'achat</Button>} />
      {fw && <div className={`mb-5 rounded-2xl border-2 border-dashed p-6 text-center text-sm transition-colors ${over ? "border-primary bg-accent" : "border-border text-muted-foreground"}`} data-testid="purchase-dropzone">Glissez-déposez un PDF ou une photo de facture ici{d.ai ? " : fournisseur, dates et montants sont lus automatiquement." : ". (Lecture automatique indisponible : assistant IA non configuré.)"}</div>}
      {!d.rows.length ? <EmptyState title="Aucune facture d'achat" /> : (
        <div className="card-soft overflow-x-auto"><table className="w-full min-w-[860px] text-sm" data-testid="purchases-table">
          <thead><tr className="border-b border-border"><th className={th}>Fournisseur</th><th className={th}>N°</th><th className={th}>Date</th><th className={th}>Échéance</th><th className={th}>HT</th><th className={th}>TVA</th><th className={th}>TTC</th><th className={th}>Statut</th><th className={th} /></tr></thead>
          <tbody>{d.rows.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-0" data-testid={`purchase-row-${r.id}`}>
              <td className={td}><div className="font-semibold">{r.supplier_name || "—"}</div><div className="text-xs text-muted-foreground">{[r.category, r.event_title].filter(Boolean).join(" · ")}</div></td>
              <td className={td}>{r.number || "—"}</td><td className={td}>{fmtDate(r.date)}</td><td className={`${td} ${r.overdue ? "font-semibold text-red-600" : ""}`}>{fmtDate(r.due_date)}</td>
              <td className={td}>{fmtEur2(r.amount_ht)}</td><td className={td}>{fmtEur2(r.vat)}</td><td className={`${td} font-semibold`}>{fmtEur2(r.amount_ttc)}</td>
              <td className={td}>{r.status === "payee" ? <Pill tone="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" testid={`purchase-status-${r.id}`}>Payée le {fmtDate(r.paid_at)}</Pill> : fw ? <Button size="sm" variant="outline" onClick={() => api.put(`/purchase-invoices/${r.id}`, { ...r, status: "payee" }).then(load).catch(ko)} data-testid={`purchase-pay-${r.id}`}>Marquer payée</Button> : <Pill>À payer</Pill>}</td>
              <td className={`${td} whitespace-nowrap text-right`}>{r.file_id && <button className="icon-btn" onClick={() => openFile(`file:${r.file_id}`)} aria-label="PDF"><Paperclip className="h-4 w-4" /></button>}
                {fw && <><button className="icon-btn" onClick={() => setEdit(r)} aria-label="Modifier" data-testid={`purchase-edit-${r.id}`}><Pencil className="h-4 w-4" /></button><button className="icon-btn" onClick={() => del("/purchase-invoices", r.id, load)} aria-label="Supprimer"><Trash2 className="h-4 w-4" /></button></>}</td>
            </tr>))}</tbody></table></div>)}
      <FormDialog testid="purchase" title={edit?.id ? "Modifier la facture d'achat" : "Nouvelle facture d'achat"} value={edit} fields={fields} onClose={() => setEdit(null)} onSubmit={(f) => save("/purchase-invoices", { ...f, lines: (f.lines || []).filter((l) => l.product_id) }, load, () => setEdit(null))}>
        {(f, setF) => <><FilePick f={f} setF={setF} kind="invoice" field="file_id" map={map} /><PurchaseLines f={f} setF={setF} /></>}
      </FormDialog>
    </div>
  );
}

export function Subscriptions() {
  const { can } = useMe();
  const [d, load] = useList("/subscriptions");
  const [edit, setEdit] = useState(null);
  if (!d) return <Loading />;
  const fw = can("finance:write");
  const fields = [{ k: "name", label: "Nom", required: true }, { k: "supplier_name", label: "Fournisseur" }, { k: "amount", label: "Montant (€)", type: "number", required: true }, { k: "period", label: "Périodicité", options: Object.entries(PERIOD) },
    { k: "renewal_date", label: "Renouvellement", type: "date" }, { k: "notice_days", label: "Préavis (jours)", type: "number" }, { k: "payment_method", label: "Moyen de paiement" }, { k: "active", label: "Actif", type: "checkbox" }];
  return (
    <div data-testid="subscriptions-page">
      <PageHeader title="Abonnements" subtitle="Logiciels, assurances, locations : une alerte apparaît au tableau de bord 30 jours avant chaque renouvellement."
        actions={fw && <Button onClick={() => setEdit({ name: "", supplier_contact_id: "", supplier_name: "", amount: "", period: "monthly", renewal_date: "", notice_days: 0, payment_method: "", active: true })} data-testid="new-subscription-button"><Plus />Abonnement</Button>} />
      <div className="mb-5 grid grid-cols-2 gap-4 sm:max-w-md"><div className="card-soft p-4"><div className="eyebrow">Total mensuel</div><div className="mt-1 font-display text-2xl" data-testid="subs-monthly">{fmtEur2(d.monthly_total)}</div></div><div className="card-soft p-4"><div className="eyebrow">Total annuel</div><div className="mt-1 font-display text-2xl" data-testid="subs-yearly">{fmtEur2(d.yearly_total)}</div></div></div>
      {!d.rows.length ? <EmptyState title="Aucun abonnement" /> : (
        <div className="card-soft divide-y divide-border">{d.rows.map((r) => (
          <div key={r.id} className={`flex flex-wrap items-center gap-3 px-5 py-4 text-sm ${r.active ? "" : "opacity-60"}`} data-testid={`subscription-row-${r.id}`}>
            <div className="min-w-0 flex-1"><div className="font-semibold">{r.name}</div><div className="text-xs text-muted-foreground">{[r.supplier_name, r.payment_method, r.notice_days ? `préavis ${r.notice_days} j` : ""].filter(Boolean).join(" · ")}</div></div>
            {r.alert && <Pill tone="bg-amber-500/15 text-amber-700 dark:text-amber-300" testid={`subscription-alert-${r.id}`}><AlertTriangle className="mr-1 inline h-3 w-3" />Renouvellement dans {r.days_left} j</Pill>}
            <span className="text-muted-foreground">{r.renewal_date ? fmtDate(r.renewal_date) : "Sans date"}</span><b>{fmtEur2(r.amount)}</b><span className="text-xs text-muted-foreground">{PERIOD[r.period]}</span>
            {fw && <><button className="icon-btn" onClick={() => setEdit(r)} aria-label="Modifier" data-testid={`subscription-edit-${r.id}`}><Pencil className="h-4 w-4" /></button><button className="icon-btn" onClick={() => del("/subscriptions", r.id, load)} aria-label="Supprimer"><Trash2 className="h-4 w-4" /></button></>}
          </div>))}</div>)}
      <FormDialog testid="subscription" title={edit?.id ? "Modifier l'abonnement" : "Nouvel abonnement"} value={edit} fields={fields} onClose={() => setEdit(null)} onSubmit={(f) => save("/subscriptions", f, load, () => setEdit(null))} />
    </div>
  );
}

export function Vehicles() {
  const { can } = useMe();
  const [rows, load] = useList("/vehicles");
  const [trash, setTrash] = useState(null);
  const [edit, setEdit] = useState(null);
  if (!rows) return <Loading />;
  const write = can("catalog:write");
  const fields = [{ k: "name", label: "Nom", required: true }, { k: "plate", label: "Immatriculation" }, { k: "capacity_kg", label: "Charge utile (kg)", type: "number" }, { k: "volume_m3", label: "Volume (m³)", type: "number" }, { k: "type", label: "Type", options: [["utilitaire", "Utilitaire"], ["porteur", "Porteur"], ["remorque", "Remorque"], ["vl", "VL"], ["location", "Location ponctuelle"]] }, { k: "licence_required", label: "Permis requis", options: ["B", "BE", "C1", "C", "CE"].map((x) => [x, x]) }, { k: "length_m", label: "Longueur hors tout (m)", type: "number" }, { k: "height_m", label: "Hauteur hors tout (m)", type: "number" }, { k: "seats", label: "Places", type: "number" }, { k: "cost_km", label: "Coût au km (€)", type: "number" }, { k: "ownership", label: "Propriété", options: [["propre", "Propre"], ["lld", "LLD"], ["location", "Location ponctuelle"]] }, { k: "tailgate", label: "Hayon", type: "checkbox" }, { k: "ct_due", label: "Contrôle technique", type: "date" }, { k: "insurance_due", label: "Assurance", type: "date" }, { k: "service_due", label: "Entretien", type: "date" }, { k: "rental_start", label: "Location du", type: "date" }, { k: "rental_end", label: "Location au", type: "date" }, { k: "rental_cost", label: "Coût de location (€)", type: "number" }, { k: "active", label: "Actif", type: "checkbox" }];
  return (
    <div data-testid="vehicles-page">
      <PageHeader title="Véhicules" subtitle="Flotte utilisée pour les chargements et les livraisons. L'affectation se fait dans Chargement du jour ou dans la vue Ressources du Planning."
        actions={write && <Button onClick={() => setEdit({ name: "", plate: "", capacity_kg: 0, volume_m3: 0, active: true, type: "utilitaire", licence_required: "B", ownership: "propre", seats: 3 })} data-testid="new-vehicle-button"><Plus />Véhicule</Button>} />
      {!rows.length ? <EmptyState title="Aucun véhicule" /> : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">{rows.map((v) => (
          <div key={v.id} className={`card-soft p-5 ${v.active ? "" : "opacity-60"}`} data-testid={`vehicle-card-${v.id}`}>
            <div className="flex items-start justify-between gap-2"><div><div className="font-medium">{v.name}</div><div className="font-mono text-xs text-muted-foreground">{v.plate || "—"}</div></div>{write && <button className="icon-btn" onClick={() => setEdit(v)} aria-label="Modifier" data-testid={`vehicle-edit-${v.id}`}><Pencil className="h-4 w-4" /></button>}{write && <button className="icon-btn text-red-600" onClick={() => setTrash(v)} aria-label="Supprimer" data-testid={`vehicle-delete-${v.id}`}><Trash2 className="h-4 w-4" /></button>}</div>
            <div className="mt-3 text-sm text-muted-foreground">{v.capacity_kg || 0} kg · {v.volume_m3 || 0} m³{v.active ? "" : " · inactif"}</div>
          </div>))}</div>)}
      <FormDialog testid="vehicle" title={edit?.id ? "Modifier le véhicule" : "Nouveau véhicule"} value={edit} fields={fields} onClose={() => setEdit(null)} onSubmit={(f) => save("/vehicles", f, load, () => setEdit(null))} />
      {trash && <TrashDialog items={[{ kind: "vehicle", id: trash.id, name: trash.name }]} onClose={() => setTrash(null)} onDone={load} />}
    </div>
  );
}
