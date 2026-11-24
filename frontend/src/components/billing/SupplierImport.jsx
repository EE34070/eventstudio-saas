import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Upload, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";
import { fmtEur2 } from "@/lib/constants";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-8 rounded-lg border border-border bg-background px-1.5 text-xs";
const TYPES = { materiel: "Matériel", service: "Service", frais: "Frais", forfait: "Forfait" };
const cost = (l) => (Number(l.unit_cost) || 0) * (1 - (Number(l.discount_percent) || 0) / 100) * (Number(l.days) || 1);
export const priceOf = (c, mode, value, rounding) => { const p = mode === "coefficient" ? c * value : c / Math.max(1 - value / 100, 0.01); return rounding ? Math.ceil(p / rounding - 1e-9) * rounding : Math.round(p * 100) / 100; };

export function SupplierImport({ quoteId, sections, spaces, file: first, onClose, onDone }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState("");
  const [o, setO] = useState({ target: "pdf_sections", section_id: "", section_title: "", space_id: "", display: "detailed", forfait_label: "", margin_mode: "coefficient", margin_value: 1.3, rounding: 0, at_cost: false, keep_margin: false, save_default: false, custom: false });
  const upload = async (file) => {
    if (!file) return;
    setBusy(true); setUrl(URL.createObjectURL(file));
    const fd = new FormData(); fd.append("file", file);
    try { const { data } = await api.post(`/supplier-quotes/extract?quote_id=${quoteId}`, fd); setD(data); setO((x) => ({ ...x, margin_mode: data.rules.mode, margin_value: data.rules.value, rounding: data.rules.rounding })); } catch (e) { ko(e); }
    setBusy(false);
  };
  useEffect(() => { if (first) upload(first); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const L = d?.lines || [];
  const up = (i, p) => setD({ ...d, lines: L.map((l, j) => (j === i ? { ...l, ...p } : l)) });
  const all = (p) => setD({ ...d, lines: L.map((l) => ({ ...l, ...(typeof p === "function" ? p(l) : p) })) });
  const kept = L.filter((l) => l.action !== "ignore");
  const sum = useMemo(() => kept.reduce((n, l) => n + (Number(l.qty) || 0) * cost(l), 0), [kept]);
  const sale = kept.reduce((n, l) => n + (Number(l.qty) || 0) * (o.at_cost ? cost(l) : priceOf(cost(l), o.margin_mode, Number(o.margin_value) || 0, o.rounding)), 0);
  const gap = d && Number(d.totals?.ht) ? Math.abs(L.reduce((n, l) => n + (Number(l.qty) || 0) * cost(l), 0) - Number(d.totals.ht)) : 0;
  const validate = async () => {
    setBusy(true);
    const body = { file_ref: d.file_ref, quote_id: quoteId, supplier: d.supplier, number: d.number, date: d.date, valid_until: d.valid_until, totals: d.totals, previous_id: d.previous?.id || "", keep_margin: o.keep_margin,
      lines: L.map((l) => ({ ...l, qty: Number(l.qty) || 1, days: Number(l.days) || 1, unit_cost: Number(l.unit_cost) || 0, discount_percent: Number(l.discount_percent) || 0, vat_rate: Number(l.vat_rate) || 0 })),
      target: o.target, section_id: o.section_id, section_title: o.section_title, space_id: o.space_id, display: o.display, forfait_label: o.forfait_label, at_cost: o.at_cost, save_default: o.save_default,
      ...(o.custom ? { margin_mode: o.margin_mode, margin_value: Number(o.margin_value) || 0, rounding: Number(o.rounding) } : {}) };
    try { const { data } = await api.post("/supplier-quotes/import", body); toast.success(`Import validé : ${data.created} article(s) créé(s), ${data.updated} mis à jour, ${data.inserted} ligne(s) ajoutée(s) au devis`); data.removed.forEach((r) => toast.warning(`Ligne retirée du devis prestataire, laissée dans votre devis : ${r}`)); if (data.pending) toast.warning(`${data.pending} ligne(s) à marge à définir`); onDone(); onClose(); } catch (e) { ko(e); }
    setBusy(false);
  };
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[96vh] max-w-[1500px] overflow-y-auto" data-testid="supplier-import-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">Importer un devis prestataire</DialogTitle><DialogDescription>PDF ou photo. L'IA lit les lignes ; rien n'est créé tant que vous n'avez pas validé. Le prestataire, ses références et ses prix ne sont jamais montrés au client.</DialogDescription></DialogHeader>
        {!d ? (
          <label onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files[0]); }} className="flex h-56 cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-border text-sm text-muted-foreground" data-testid="supplier-import-drop">
            {busy ? <><Loader2 className="h-6 w-6 animate-spin" />Lecture du document par l'IA (jusqu'à une minute)…</> : <><Upload className="h-6 w-6" />Glissez le devis ici ou cliquez pour le choisir (PDF, JPEG, PNG — 15 Mo max)</>}
            <input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" className="hidden" disabled={busy} onChange={(e) => upload(e.target.files[0])} data-testid="supplier-import-file" />
          </label>
        ) : (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
            <iframe title="Devis prestataire" src={url} className="h-[70vh] w-full rounded-xl border border-border xl:col-span-2" data-testid="supplier-import-preview" />
            <div className="space-y-3 text-sm xl:col-span-3">
              <div className="flex flex-wrap items-center gap-2" data-testid="supplier-import-header">
                <b>Prestataire</b><Input className="h-8 w-56" value={d.supplier.name} disabled={d.supplier.known} onChange={(e) => setD({ ...d, supplier: { ...d.supplier, name: e.target.value } })} data-testid="supplier-import-name" />
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${d.supplier.known ? "bg-emerald-50 text-emerald-700" : "bg-amber-500/15 text-amber-700"}`} data-testid="supplier-import-known">{d.supplier.known ? "Reconnu" : "Nouveau contact à créer"}</span>
                <span>N° <Input className="inline h-8 w-32" value={d.number} onChange={(e) => setD({ ...d, number: e.target.value })} /></span><span className="text-xs text-muted-foreground">{d.date}{d.valid_until ? ` · valable jusqu'au ${d.valid_until}` : ""}</span>
              </div>
              {d.previous && <div className="rounded-xl border border-blue-500/40 bg-blue-500/10 p-2 text-xs" data-testid="supplier-import-diff"><b>Nouvelle version du devis {d.previous.number} (V{d.previous.version + 1})</b> : {d.previous.added.length} ajoutée(s){d.previous.added.length ? ` (${d.previous.added.join(", ")})` : ""}, {d.previous.removed.length} retirée(s), {d.previous.changed.length} prix modifié(s){d.previous.changed.map((c) => ` · ${c.label} : ${c.old} → ${c.new}`).join("")}.
                <label className="mt-1 flex items-center gap-2"><input type="checkbox" checked={o.keep_margin} onChange={(e) => setO({ ...o, keep_margin: e.target.checked })} data-testid="supplier-import-keep-margin" />Conserver ma marge % (sinon mes prix de vente restent inchangés)</label></div>}
              {(d.checks.length > 0 || gap > 0.05) && <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-2 text-xs text-amber-800" data-testid="supplier-import-checks">{d.checks.map((c) => <div key={c.message}>{c.message}</div>)}{gap > 0.05 && <div>Écart actuel avec le total HT du document : {fmtEur2(gap)}</div>}</div>}
              <div className="flex flex-wrap gap-2 text-xs"><button type="button" className="underline" onClick={() => all((l) => ({ action: l.equipment_id ? "existing" : "new" }))} data-testid="supplier-import-accept-all">Tout accepter</button>
                <select className={sel} value="" onChange={(e) => e.target.value && all({ family: e.target.value })} aria-label="Famille pour toutes les lignes"><option value="">Famille pour toutes…</option>{d.families.map((f) => <option key={f}>{f}</option>)}</select></div>
              <div className="max-h-[38vh] overflow-auto rounded-xl border border-border"><table className="w-full text-xs" data-testid="supplier-import-lines">
                <thead><tr className="border-b border-border text-left text-muted-foreground"><th className="p-1.5">Catalogue</th><th className="p-1.5">Désignation prestataire → libellé client</th><th className="p-1.5">Type / famille</th><th className="p-1.5">Qté</th><th className="p-1.5">Jours</th><th className="p-1.5">PU HT</th><th className="p-1.5">Rem. %</th><th className="p-1.5 text-right">Coût</th></tr></thead>
                <tbody>{L.map((l, i) => { const low = l.confidence < 0.7 || d.checks.some((c) => c.line === i); return (
                  <tr key={i} className={`border-b border-border last:border-0 ${l.action === "ignore" ? "opacity-40" : ""} ${low ? "bg-amber-500/10" : ""}`} data-testid={`supplier-line-${i}`}>
                    <td className="p-1.5"><select className={sel} value={l.action} onChange={(e) => up(i, { action: e.target.value })} data-testid={`supplier-line-action-${i}`}>{l.equipment_id && <option value="existing">Existant</option>}<option value="new">Nouveau</option><option value="ignore">Ignorer</option></select>{l.action === "existing" && l.old_cost != null && <div className="mt-0.5 text-[10px] text-muted-foreground">{l.old_cost} → {l.unit_cost} €</div>}</td>
                    <td className="p-1.5"><div className="text-muted-foreground">{l.ref ? `${l.ref} · ` : ""}{l.label}{l.section ? ` — ${l.section}` : ""}</div><Input className="mt-0.5 h-7 text-xs" value={l.client_label} onChange={(e) => up(i, { client_label: e.target.value })} data-testid={`supplier-line-label-${i}`} /></td>
                    <td className="p-1.5"><select className={sel} value={l.type} onChange={(e) => up(i, { type: e.target.value })} data-testid={`supplier-line-type-${i}`}>{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select><select className={`${sel} mt-0.5`} value={l.family} onChange={(e) => up(i, { family: e.target.value })}>{[...new Set([...d.families, l.family])].map((f) => <option key={f}>{f}</option>)}</select></td>
                    {["qty", "days", "unit_cost", "discount_percent"].map((k) => <td key={k} className="p-1.5"><Input type="number" step="any" className="h-7 w-16 text-xs" value={l[k]} onChange={(e) => up(i, { [k]: e.target.value })} data-testid={`supplier-line-${k}-${i}`} /></td>)}
                    <td className="p-1.5 text-right font-semibold">{fmtEur2((Number(l.qty) || 0) * cost(l))}</td>
                  </tr>); })}</tbody></table></div>
              <div className="grid grid-cols-1 gap-2 rounded-xl border border-border p-2 sm:grid-cols-2" data-testid="supplier-import-options">
                <label className="flex items-center gap-2">Section cible<select className={sel} value={o.target === "existing" ? o.section_id : o.target} onChange={(e) => (["pdf_sections", "new"].includes(e.target.value) ? setO({ ...o, target: e.target.value, section_id: "" }) : setO({ ...o, target: "existing", section_id: e.target.value }))} data-testid="supplier-import-target"><option value="pdf_sections">Sections du PDF</option><option value="new">Nouvelle section</option>{sections.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>
                {o.target !== "existing" && <label className="flex items-center gap-2">{o.target === "new" ? "Titre" : "Titre si ligne sans section"}<Input className="h-8" value={o.section_title} onChange={(e) => setO({ ...o, section_title: e.target.value })} data-testid="supplier-import-section-title" /></label>}
                {spaces.length > 0 && o.target !== "existing" && <label className="flex items-center gap-2">Emplacement<select className={sel} value={o.space_id} onChange={(e) => setO({ ...o, space_id: e.target.value })} data-testid="supplier-import-space"><option value="">Aucun</option>{spaces.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>}
                <label className="flex items-center gap-2">Affichage<select className={sel} value={o.display} onChange={(e) => setO({ ...o, display: e.target.value })} data-testid="supplier-import-display"><option value="detailed">Lignes détaillées</option><option value="forfait">Un seul forfait (détail gardé en interne)</option></select></label>
                {o.display === "forfait" && <label className="flex items-center gap-2">Libellé du forfait<Input className="h-8" value={o.forfait_label} onChange={(e) => setO({ ...o, forfait_label: e.target.value })} data-testid="supplier-import-forfait-label" /></label>}
                <label className="flex items-center gap-2 sm:col-span-2"><input type="checkbox" checked={o.at_cost} onChange={(e) => setO({ ...o, at_cost: e.target.checked })} data-testid="supplier-import-at-cost" />Insérer au prix coûtant (marge à définir ensuite)</label>
                {!o.at_cost && <div className="flex flex-wrap items-center gap-2 sm:col-span-2"><label className="flex items-center gap-1"><input type="checkbox" checked={o.custom} onChange={(e) => setO({ ...o, custom: e.target.checked })} data-testid="supplier-import-custom-margin" />Marge pour tout l'import</label>
                  {o.custom ? <><select className={sel} value={o.margin_mode} onChange={(e) => setO({ ...o, margin_mode: e.target.value, margin_value: e.target.value === "coefficient" ? 1.3 : 30 })} data-testid="supplier-import-margin-mode"><option value="coefficient">Coefficient sur coût</option><option value="markup">Taux de marque %</option></select>
                    <Input type="number" step="any" className="h-8 w-20" value={o.margin_value} onChange={(e) => setO({ ...o, margin_value: e.target.value })} data-testid="supplier-import-margin-value" />
                    <select className={sel} value={o.rounding} onChange={(e) => setO({ ...o, rounding: Number(e.target.value) })} data-testid="supplier-import-rounding"><option value={0}>Sans arrondi</option><option value={1}>À l'euro</option><option value={5}>À 5 €</option><option value={10}>À 10 €</option></select>
                    <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={o.save_default} onChange={(e) => setO({ ...o, save_default: e.target.checked })} />Enregistrer comme défaut</label></> : <span className="text-xs text-muted-foreground">sinon : marges par défaut (prestataire, famille, puis société : {d.rules.mode === "coefficient" ? `× ${d.rules.value}` : `${d.rules.value} %`})</span>}</div>}
              </div>
              <div className="flex flex-wrap justify-end gap-4 font-semibold" data-testid="supplier-import-totals"><span>Coût : {fmtEur2(sum)} HT</span>{o.custom || o.at_cost ? <span>Vente : {fmtEur2(sale)} HT · marge {fmtEur2(sale - sum)}</span> : null}<span className="text-muted-foreground">Total du document : {fmtEur2(Number(d.totals?.ht) || 0)}</span></div>
            </div>
          </div>
        )}
        {d && <DialogFooter><Button variant="outline" onClick={onClose}>Annuler</Button><Button disabled={busy || !kept.length} onClick={validate} data-testid="supplier-import-validate">{busy ? "Import…" : "Valider l'import"}</Button></DialogFooter>}
      </DialogContent>
    </Dialog>
  );
}

export function SupplierQuotes({ rows }) {
  const draft = (s) => api.get(`/supplier-quotes/${s.id}/order-draft`).then((r) => { navigator.clipboard?.writeText(`${r.data.subject}\n\n${r.data.body}`); window.prompt(`Confirmation de commande pour ${s.supplier_name} (${r.data.to || "sans e-mail"}) — texte copié, rien n'est envoyé :`, `${r.data.subject} — ${r.data.body}`); }).catch(ko);
  if (!rows?.length) return null;
  return (
    <div className="rounded-2xl border border-border p-3 text-sm" data-testid="supplier-quotes-list"><div className="mb-1 font-semibold">Devis prestataires importés (interne)</div>
      {rows.map((s) => <div key={s.id} className="flex flex-wrap items-center gap-3 py-1" data-testid={`supplier-quote-${s.id}`}><b>{s.supplier_name}</b><span>n° {s.number || "—"} · V{s.version} · {fmtEur2(s.cost_total)} HT · {s.status}</span><span className="ml-auto" />
        <a className="text-xs underline" href="#pdf" onClick={(e) => { e.preventDefault(); api.get(`/files/${s.file_ref.slice(5)}`, { responseType: "blob" }).then((r) => window.open(URL.createObjectURL(r.data))).catch(ko); }}>Voir le PDF</a>
        <button type="button" className="text-xs underline" onClick={() => draft(s)} data-testid={`supplier-quote-order-${s.id}`}>Préparer la commande</button></div>)}
    </div>
  );
}
