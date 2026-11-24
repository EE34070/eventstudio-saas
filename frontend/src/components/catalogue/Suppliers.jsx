import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Mail, Plus, Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";

const ko = (e) => toast.error(errMsg(e));
const eur = (v, d = 2) => (v == null ? "—" : `${Number(v).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: 4 })} €`);
const BLANK = { supplier_id: "", supplier_ref: "", supplier_label: "", purchase_uom: "", conversion_factor: 1, unit_price_ht: "", price_date: "", lead_time_days: "", min_order_qty: "", usual_shipping_ht: "", url: "", notes: "", is_preferred: false };
const NUMS = ["unit_price_ht", "lead_time_days", "min_order_qty", "usual_shipping_ht"];
const body = (f) => ({ ...f, conversion_factor: Number(String(f.conversion_factor).replace(",", ".")) || 1, ...Object.fromEntries(NUMS.map((k) => [k, f[k] === "" || f[k] == null ? null : Number(String(f[k]).replace(",", "."))])) });
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const nameOf = (c) => c.company || [c.first_name, c.last_name].filter(Boolean).join(" ");

function SupplierPick({ value, onChange }) {
  const [list, setList] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [nw, setNw] = useState(null);
  useEffect(() => { api.get("/contacts", { params: { type: "fournisseur" } }).then((r) => setList(r.data)).catch(() => {}); }, []);
  const hits = list.filter((c) => nameOf(c).toLowerCase().includes(q.toLowerCase())).slice(0, 8);
  if (nw) return (
    <div className="col-span-4 grid grid-cols-3 gap-2 rounded-xl border border-border p-3" data-testid="supplier-new-form">
      {[["name", "Nom"], ["company", "Société *"], ["email", "E-mail"], ["phone", "Téléphone"], ["website", "Site web"]].map(([k, l]) => <Input key={k} placeholder={l} value={nw[k]} onChange={(e) => { const x = { ...nw, [k]: e.target.value }; setNw(x); onChange({ supplier_id: "", new_supplier: x }); }} data-testid={`supplier-new-${k}`} />)}
      <select className={sel} value={nw.language} onChange={(e) => { const x = { ...nw, language: e.target.value }; setNw(x); onChange({ supplier_id: "", new_supplier: x }); }} data-testid="supplier-new-language"><option value="fr-FR">Français</option><option value="en-GB">English</option></select>
    </div>);
  return (
    <div className="relative col-span-2"><Input placeholder="Fournisseur *" value={value.label ?? q} onChange={(e) => { setQ(e.target.value); setOpen(true); onChange({ supplier_id: "", label: undefined }); }} onFocus={() => setOpen(true)} data-testid="supplier-pick" />
      {open && <div className="absolute z-30 mt-1 w-full rounded-xl border border-border bg-card p-1 shadow-lg">
        {hits.map((c) => <button key={c.id} type="button" className="block w-full rounded-lg px-3 py-1.5 text-left text-sm hover:bg-secondary" onClick={() => { onChange({ supplier_id: c.id, label: nameOf(c) }); setOpen(false); }} data-testid={`supplier-option-${c.id}`}>{nameOf(c)}</button>)}
        {q.trim() && <button type="button" className="block w-full rounded-lg px-3 py-1.5 text-left text-sm font-semibold text-primary hover:bg-secondary" onClick={() => { const x = { name: "", company: q.trim(), email: "", phone: "", website: "", language: "fr-FR" }; setNw(x); onChange({ supplier_id: "", new_supplier: x }); setOpen(false); }} data-testid="supplier-create">+ Créer le fournisseur « {q.trim()} »</button>}</div>}
    </div>);
}

function Form({ f, setF, withSupplier, uom }) {
  const t = (k, ph, cls = "", type = "text") => <Input className={cls} type={type} placeholder={ph} title={ph} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`sup-${k}`} />;
  return (
    <div className="grid grid-cols-4 gap-2">
      {withSupplier && <SupplierPick value={f} onChange={(x) => setF({ ...f, ...x })} />}
      {t("supplier_ref", "Référence fournisseur")}{t("supplier_label", "Désignation chez le fournisseur")}
      {t("purchase_uom", "Unité d'achat (ex. rouleau 2 × 25 m)")}{t("conversion_factor", `1 unité d'achat = … ${uom}`)}{t("unit_price_ht", "Prix d'achat HT (par unité d'achat)")}{t("price_date", "Date du prix", "", "date")}
      {t("lead_time_days", "Délai (jours)")}{t("min_order_qty", "Minimum de commande")}{t("usual_shipping_ht", "Frais de port HT")}{t("url", "Lien page produit")}
      {t("notes", "Notes (couleurs dispo…)", "col-span-3")}<label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={!!f.is_preferred} onChange={(e) => setF({ ...f, is_preferred: e.target.checked })} data-testid="sup-preferred" />Préféré</label>
    </div>);
}

export function SuppliersTab({ item, write }) {
  const nav = useNavigate();
  const [rows, setRows] = useState(null);
  const [f, setF] = useState(null);
  const [hist, setHist] = useState(null);
  const load = useCallback(() => api.get(`/equipment/${item.id}/suppliers`).then((r) => setRows(r.data)).catch((e) => { setRows([]); ko(e); }), [item.id]);
  useEffect(() => { load(); }, [load]);
  const uom = item.stock_uom || "pièce";
  const save = () => (f.id ? api.put(`/supplier-products/${f.id}`, body(f)) : api.post(`/equipment/${item.id}/suppliers`, body(f))).then((r) => { setRows(r.data); setF(null); toast.success("Fournisseur enregistré"); }).catch(ko);
  const ask = (m) => api.get(`/supplier-products/${m.id}/price-request`, { params: { qty: m.min_order_qty || 1 } }).then((r) => nav(`/messagerie?compose=1&to=${encodeURIComponent(r.data.to)}&subject=${encodeURIComponent(r.data.subject)}&text=${encodeURIComponent(r.data.text)}`)).catch(ko);
  if (!rows) return null;
  return (
    <div className="space-y-3 text-sm" data-testid="suppliers-tab">
      {!rows.length && <p className="text-muted-foreground">Aucun fournisseur pour ce produit.</p>}
      {rows.map((m) => (
        <div key={m.id} className="rounded-xl border border-border p-3" data-testid={`sup-row-${m.id}`}>
          <div className="flex flex-wrap items-center gap-2">
            <button title="Fournisseur préféré" disabled={!write} onClick={() => api.put(`/supplier-products/${m.id}`, { ...body(m), is_preferred: true }).then((r) => setRows(r.data)).catch(ko)} data-testid={`sup-star-${m.id}`}><Star className={`h-4 w-4 ${m.is_preferred ? "fill-amber-400 text-amber-500" : "text-muted-foreground"}`} /></button>
            <b data-testid={`sup-name-${m.id}`}>{m.supplier_name}</b>
            {m.is_preferred && <span className="rounded-full bg-amber-500/15 px-2 text-xs text-amber-700" data-testid={`sup-preferred-${m.id}`}>préféré</span>}
            {m.cheapest && <span className="rounded-full bg-emerald-500/15 px-2 text-xs text-emerald-700" data-testid={`sup-cheapest-${m.id}`}>moins cher</span>}
            {m.source !== "manual" && <span className="rounded-full bg-sky-500/15 px-2 text-xs text-sky-700" data-testid={`sup-learned-${m.id}`}>{m.source === "invoice" ? "appris d'une facture" : "appris d'un devis"}</span>}
            <span className="flex-1" />
            <b data-testid={`sup-stock-price-${m.id}`}>{eur(m.stock_price_ht)} HT / {uom}</b>
            {write && <><Button size="sm" variant="ghost" onClick={() => ask(m)} data-testid={`sup-ask-${m.id}`}><Mail />Demander un prix</Button>
              <button className="text-xs underline" onClick={() => setF({ ...BLANK, ...Object.fromEntries(Object.entries(m).map(([k, v]) => [k, v ?? ""])) })} data-testid={`sup-edit-${m.id}`}>Modifier</button>
              <button aria-label="Supprimer" onClick={() => window.confirm("Retirer ce fournisseur du produit ?") && api.delete(`/supplier-products/${m.id}`).then((r) => setRows(r.data)).catch(ko)} data-testid={`sup-delete-${m.id}`}><Trash2 className="h-4 w-4" /></button></>}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">{[m.supplier_ref && `réf. ${m.supplier_ref}`, m.supplier_label, m.unit_price_ht != null && `${eur(m.unit_price_ht)} HT / ${m.purchase_uom || uom}`, m.conversion_factor !== 1 && `1 ${m.purchase_uom || "unité"} = ${m.conversion_factor} ${uom}`, m.price_date && `prix du ${fmtDate(m.price_date)}`,
            m.lead_time_days != null && `délai ${m.lead_time_days} j`, m.min_order_qty != null && `mini ${m.min_order_qty}`, m.usual_shipping_ht != null && `port ${eur(m.usual_shipping_ht)}`, m.notes].filter(Boolean).join(" · ")}
            {m.url && <> · <a className="underline" href={m.url} target="_blank" rel="noreferrer">page produit</a></>} · <button className="underline" onClick={() => api.get(`/supplier-products/${m.id}/history`).then((r) => setHist({ id: m.id, rows: r.data })).catch(ko)} data-testid={`sup-history-${m.id}`}>historique</button></div>
          {hist?.id === m.id && <div className="mt-1 text-xs" data-testid={`sup-history-list-${m.id}`}>{hist.rows.map((h) => <div key={h.id}>{h.date ? fmtDate(h.date) : "—"} : {eur(h.price)} ({h.source === "invoice" ? "facture" : h.source === "quote" ? "devis" : "saisie"})</div>)}</div>}
        </div>))}
      {f ? <div className="space-y-2 rounded-xl border border-primary/40 p-3" data-testid="sup-form"><Form f={f} setF={setF} withSupplier={!f.id} uom={uom} />
        <div className="flex justify-end gap-2"><Button size="sm" variant="ghost" onClick={() => setF(null)}>Annuler</Button><Button size="sm" disabled={!f.id && !f.supplier_id && !f.new_supplier?.company} onClick={save} data-testid="sup-save">Enregistrer</Button></div></div>
        : write && <Button size="sm" variant="outline" onClick={() => setF({ ...BLANK })} data-testid="sup-add"><Plus />Ajouter un fournisseur</Button>}
    </div>);
}

export function SupplierProducts({ contactId, write }) {
  const [d, setD] = useState(null);
  const [eqs, setEqs] = useState(null);
  const [pick, setPick] = useState("");
  const load = useCallback(() => api.get("/supplier-products", { params: { supplier_id: contactId } }).then((r) => setD(r.data)).catch(() => setD({ rows: [], allowed: false })), [contactId]);
  useEffect(() => { load(); }, [load]);
  if (!d?.allowed) return null;
  return (
    <div data-testid="supplier-products"><div className="eyebrow mb-2">Produits ({d.rows.length})</div>
      {d.rows.map((m) => <div key={m.id} className="flex items-center justify-between border-b border-border py-1.5 text-sm last:border-0" data-testid={`supplier-product-${m.product_id}`}>
        <Link className="underline" to={`/catalogue?q=${encodeURIComponent(m.product_ref)}`}>{m.product_ref} {m.product_name}</Link>
        <span className="text-xs text-muted-foreground">{[m.supplier_ref && `réf. ${m.supplier_ref}`, m.unit_price_ht != null && `${eur(m.unit_price_ht)} HT`, m.price_date && fmtDate(m.price_date)].filter(Boolean).join(" · ")}</span></div>)}
      {write && (eqs ? <div className="mt-2 flex gap-2"><select className={`${sel} min-w-0 flex-1`} value={pick} onChange={(e) => setPick(e.target.value)} data-testid="supplier-product-select"><option value="">Choisir un produit…</option>{eqs.map((e) => <option key={e.id} value={e.id}>{e.ref} {e.name}</option>)}</select>
        <Button size="sm" disabled={!pick} onClick={() => api.post("/supplier-products", { supplier_id: contactId, product_id: pick }).then(() => { setPick(""); load(); toast.success("Produit lié"); }).catch(ko)} data-testid="supplier-product-add-confirm">Lier</Button></div>
        : <button className="mt-2 text-sm underline" onClick={() => api.get("/equipment").then((r) => setEqs(r.data.items)).catch(ko)} data-testid="supplier-product-add">+ Ajouter un produit</button>)}
    </div>);
}

export const Offers = ({ offers, testid }) => (!offers?.length ? null : (
  <div className="mt-1 flex flex-wrap gap-1.5 text-xs" data-testid={testid}><span className="text-muted-foreground">Commander chez :</span>
    {offers.map((o) => <span key={o.id} className={`rounded-full border px-2 py-0.5 ${o.is_preferred ? "border-amber-500/50 bg-amber-500/10" : "border-border"}`} data-testid={`${testid}-${o.supplier_id}`}>{o.is_preferred ? "★ " : ""}{o.supplier_name}{o.unit_price_ht != null ? ` · ${eur(o.unit_price_ht)} HT / ${o.purchase_uom || o.stock_uom}` : ""}{o.lead_time_days != null ? ` · ${o.lead_time_days} j` : ""}{o.usual_shipping_ht != null ? ` · port ${eur(o.usual_shipping_ht)}` : ""}</span>)}</div>));

export function PurchaseLines({ f, setF }) {
  const [eqs, setEqs] = useState([]);
  useEffect(() => { api.get("/equipment").then((r) => setEqs(r.data.items)).catch(() => {}); }, []);
  const lines = f.lines || [];
  const up = (i, k, v) => setF({ ...f, lines: lines.map((x, j) => (j === i ? { ...x, [k]: v } : x)) });
  return (
    <div className="col-span-2 space-y-2" data-testid="purchase-lines"><div className="text-xs text-muted-foreground">Lignes produit (facultatif) : met à jour le prix d'achat de ce fournisseur pour chaque produit. Choisissez un fournisseur (contact).</div>
      {lines.map((l, i) => <div key={i} className="flex gap-2"><select className={`${sel} min-w-0 flex-1`} value={l.product_id} onChange={(e) => up(i, "product_id", e.target.value)} data-testid={`purchase-line-product-${i}`}><option value="">Produit…</option>{eqs.map((e) => <option key={e.id} value={e.id}>{e.ref} {e.name}</option>)}</select>
        <Input className="w-20" type="number" min="0" step="any" title="Quantité" value={l.qty} onChange={(e) => up(i, "qty", Number(e.target.value))} /><Input className="w-28" type="number" min="0" step="any" placeholder="PU HT" title="Prix unitaire HT (unité d'achat)" value={l.unit_price_ht} onChange={(e) => up(i, "unit_price_ht", Number(e.target.value))} data-testid={`purchase-line-price-${i}`} />
        <button type="button" aria-label="Supprimer" onClick={() => setF({ ...f, lines: lines.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button></div>)}
      <button type="button" className="text-sm underline" onClick={() => setF({ ...f, lines: [...lines, { product_id: "", qty: 1, unit_price_ht: 0 }] })} data-testid="purchase-line-add">+ Ligne produit</button></div>);
}
