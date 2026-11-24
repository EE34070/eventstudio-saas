import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, FileText, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { UploadButton, openFile } from "@/lib/files";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { UnitsTab, AttrsTab } from "@/components/catalogue/Units";
import { SuppliersTab } from "@/components/catalogue/Suppliers";
import { useMe } from "@/context/MeContext";

const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
export const DOC = { fiche_technique: "Fiche technique", notice: "Notice d'utilisation", fiche_commerciale: "Fiche commerciale", certificat: "Certificat / conformité", autre: "Autre" };
export const REQ = { consommable: "Consommable", accessoire_obligatoire: "Accessoire obligatoire", accessoire_optionnel: "Accessoire optionnel", alimentation: "Alimentation électrique", logistique: "Logistique", humain: "Humain", note: "Note libre" };
const MODES = { per_unit: "par unité", per_unit_day: "par unité et par jour", per_event: "par événement", per_day: "par jour", per_hour: "par heure", per_secondary: "par unité secondaire (m, m²…)" };
const BLANK = { id: "", type: "consommable", label: "", label_en: "", linked_product_id: "", quantity: 1, unit: "", calc_mode: "per_unit", spare_qty: 0, spare_pct: 0, mandatory: true, power_w: 0, voltage: "", plug_type: "", sockets: 0, weight_kg: 0, volume_m3: 0, handlers: 0, setup_min: 0, teardown_min: 0, note: "" };
const NUMS = ["quantity", "spare_qty", "spare_pct", "power_w", "sockets", "weight_kg", "volume_m3", "handlers", "setup_min", "teardown_min"];
const EXTRA = {
  alimentation: [["voltage", "Tension (230 V)", "text"], ["power_w", "Puissance W"], ["plug_type", "Type de prise", "text"], ["sockets", "Nb prises"]],
  logistique: [["weight_kg", "Poids kg"], ["volume_m3", "Volume m³"], ["handlers", "Personnes"]],
  humain: [["handlers", "Techniciens"], ["setup_min", "Install. min"], ["teardown_min", "Démont. min"]],
};
const LINKED = ["consommable", "accessoire_obligatoire", "accessoire_optionnel"];
const ko = (e) => toast.error(errMsg(e));
const blob = async (ref) => URL.createObjectURL((await api.get(`/files/${ref.slice(5)}`, { responseType: "blob" })).data);
const download = async (ref, name) => { try { const a = document.createElement("a"); a.href = await blob(ref); a.download = `${name}.pdf`; a.click(); } catch { toast.error("Fichier introuvable"); } };

function DocsTab({ item, equipment, write, admin, onSaved }) {
  const [docs, setDocs] = useState([]);
  const [all, setAll] = useState([]);
  const [nw, setNw] = useState({ type: "fiche_technique", title: "", visibility: "interne" });
  const [view, setView] = useState(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.get("/product-documents").then((r) => { setAll(r.data); setDocs(r.data.filter((d) => d.product_ids.includes(item.id))); }).catch(ko), [item.id]);
  useEffect(() => { load(); }, [load]);
  const run = async (fn, msg) => { try { await fn(); if (msg) toast.success(msg); await load(); onSaved?.(); } catch (e) { ko(e); } };
  const add = (refs) => run(async () => { for (const [i, f] of refs.entries()) await api.post("/product-documents", { file_ref: f, title: nw.title.trim() || item.name, type: nw.type, visibility: nw.visibility, is_primary: !docs.length && i === 0, product_ids: [item.id] }); setNw({ ...nw, title: "" }); }, "Document ajouté");
  const drop = async (e) => {
    e.preventDefault(); setOver(false);
    const files = [...e.dataTransfer.files].filter((f) => f.type === "application/pdf");
    if (!files.length) { toast.error("Déposez un fichier PDF"); return; }
    setBusy(true);
    const refs = [];
    for (const file of files) { const fd = new FormData(); fd.append("file", file); try { refs.push((await api.post("/files", fd)).data.ref); } catch (err) { toast.error(`${file.name} : ${errMsg(err)}`); } }
    setBusy(false);
    if (refs.length) add(refs);
  };
  const preview = async (d, ref) => { try { setView({ title: d.title, url: await blob(ref) }); } catch { toast.error("Fichier introuvable"); } };
  const others = all.filter((d) => !d.product_ids.includes(item.id));
  return (
    <div className="space-y-2 text-sm" data-testid="product-docs">
      {!docs.length && <p className="text-muted-foreground">Aucun document pour ce produit.</p>}
      {docs.map((d) => (<div key={d.id} className="rounded-xl border border-border p-3" data-testid={`product-doc-${d.id}`}>
        <div className="flex flex-wrap items-center gap-2"><FileText className="h-4 w-4" /><b>{d.title}</b><span className="text-muted-foreground">{DOC[d.type]} · v{d.version} · {d.uploaded_by} · {new Date(d.created_at).toLocaleDateString("fr-FR")}</span>
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${d.visibility === "client" ? "bg-emerald-500/10 text-emerald-700" : "bg-secondary"}`} data-testid={`product-doc-visibility-${d.id}`}>{d.visibility === "client" ? "Partageable client" : "Interne"}</span>{d.is_primary && <span className="text-xs font-semibold text-primary" data-testid={`product-doc-primary-${d.id}`}>Principal</span>}
          <span className="flex-1" /><button className="underline" onClick={() => preview(d, d.file_ref)} data-testid={`product-doc-open-${d.id}`}>Aperçu</button>
          <button aria-label="Télécharger" onClick={() => download(d.file_ref, d.title)} data-testid={`product-doc-download-${d.id}`}><Download className="h-4 w-4" /></button></div>
        {write && <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <Input className="h-8 w-48" defaultValue={d.title} key={d.title} aria-label="Titre" onBlur={(e) => e.target.value.trim() && e.target.value !== d.title && run(() => api.patch(`/product-documents/${d.id}`, { title: e.target.value.trim() }))} data-testid={`product-doc-title-${d.id}`} />
          <select className={`${sel} h-8`} value={d.type} onChange={(e) => run(() => api.patch(`/product-documents/${d.id}`, { type: e.target.value }))} aria-label="Type">{Object.entries(DOC).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <select className={`${sel} h-8`} value={d.visibility} onChange={(e) => run(() => api.patch(`/product-documents/${d.id}`, { visibility: e.target.value }))} aria-label="Visibilité" data-testid={`product-doc-vis-${d.id}`}><option value="interne">Interne</option><option value="client">Partageable client</option></select>
          <label className="flex items-center gap-1"><input type="checkbox" checked={d.is_primary} onChange={(e) => run(() => api.patch(`/product-documents/${d.id}`, { is_primary: e.target.checked }))} data-testid={`product-doc-setprimary-${d.id}`} />Principal</label>
          <UploadButton accept="application/pdf" multiple={false} label="Remplacer" testid={`product-doc-replace-${d.id}`} onUploaded={(r) => run(() => api.patch(`/product-documents/${d.id}`, { file_ref: r[0] }), "Nouvelle version enregistrée, l'ancienne reste dans l'historique")} />
          <select className={`${sel} h-8`} value="" onChange={(e) => e.target.value && run(() => api.patch(`/product-documents/${d.id}`, { product_ids: [...d.product_ids, e.target.value] }), "Document lié à l'autre produit")} data-testid={`product-doc-link-${d.id}`}><option value="">Lier aussi à… ({d.product_ids.length} produit{d.product_ids.length > 1 ? "s" : ""})</option>{equipment.filter((x) => !d.product_ids.includes(x.id)).map((x) => <option key={x.id} value={x.id}>{x.ref} {x.name}</option>)}</select>
          {d.product_ids.length > 1 && <button className="underline" onClick={() => run(() => api.patch(`/product-documents/${d.id}`, { product_ids: d.product_ids.filter((i) => i !== item.id) }), "Document retiré de ce produit")} data-testid={`product-doc-unlink-${d.id}`}>Retirer de ce produit</button>}
          {admin && <button aria-label="Supprimer" onClick={() => window.confirm("Supprimer ce document pour tous les produits liés ?") && run(() => api.delete(`/product-documents/${d.id}`), "Document supprimé")} data-testid={`product-doc-delete-${d.id}`}><Trash2 className="h-4 w-4" /></button>}</div>}
        {d.history.map((h) => <div key={h.version} className="mt-1 text-xs text-muted-foreground" data-testid={`product-doc-history-${d.id}-${h.version}`}>Ancienne version v{h.version} (remplacée le {new Date(h.replaced_at).toLocaleDateString("fr-FR")} par {h.by}) — <button className="underline" onClick={() => preview(d, h.file_ref)}>aperçu</button></div>)}
      </div>))}
      {write && <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop} className={`flex flex-wrap items-center gap-2 rounded-xl border-2 border-dashed p-3 ${over ? "border-primary bg-primary/5" : "border-border"}`} data-testid="product-doc-dropzone">
        <select className={sel} value={nw.type} onChange={(e) => setNw({ ...nw, type: e.target.value })} data-testid="product-doc-new-type">{Object.entries(DOC).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <Input className="h-9 w-56" placeholder="Titre (sinon nom du produit)" value={nw.title} onChange={(e) => setNw({ ...nw, title: e.target.value })} data-testid="product-doc-new-title" />
        <select className={sel} value={nw.visibility} onChange={(e) => setNw({ ...nw, visibility: e.target.value })} data-testid="product-doc-new-visibility"><option value="interne">Interne</option><option value="client">Partageable client</option></select>
        <UploadButton accept="application/pdf" multiple label="Ajouter un PDF (20 Mo max)" testid="product-doc-upload" onUploaded={add} />
        <span className="text-xs text-muted-foreground">{busy ? "Envoi…" : "ou glissez-déposez vos PDF ici"}</span>
        {others.length > 0 && <select className={`${sel} ml-auto`} value="" onChange={(e) => { const d = others.find((x) => x.id === e.target.value); if (d) run(() => api.patch(`/product-documents/${d.id}`, { product_ids: [...d.product_ids, item.id] }), "Document existant lié à ce produit"); }} data-testid="product-doc-link-existing"><option value="">Lier un PDF existant…</option>{others.map((d) => <option key={d.id} value={d.id}>{d.title} ({DOC[d.type]})</option>)}</select>}
      </div>}
      {view && <Dialog open onOpenChange={() => { URL.revokeObjectURL(view.url); setView(null); }}><DialogContent className="h-[90vh] max-w-5xl" data-testid="product-doc-preview"><DialogHeader><DialogTitle>{view.title}</DialogTitle><DialogDescription className="sr-only">Aperçu du document PDF</DialogDescription></DialogHeader><iframe title={view.title} src={view.url} className="h-[78vh] w-full rounded-lg border border-border" /></DialogContent></Dialog>}
    </div>
  );
}

function ReqsTab({ item, equipment, write, onSaved }) {
  const [reqs, setReqs] = useState(item.requirements || []);
  const [tpls, setTpls] = useState([]);
  const loadT = useCallback(() => api.get("/requirement-templates").then((r) => setTpls(r.data)).catch(() => {}), []);
  useEffect(() => { loadT(); }, [loadT]);
  const up = (i, k, v) => setReqs(reqs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const num = (r) => ({ ...BLANK, ...r, ...Object.fromEntries(NUMS.map((k) => [k, Number(r[k]) || 0])) });
  const clean = () => reqs.filter((r) => r.label.trim()).map(num);
  const save = () => api.put(`/equipment/${item.id}/requirements`, { requirements: clean() }).then((r) => { setReqs(r.data); toast.success("Besoins enregistrés"); onSaved?.(); }).catch(ko);
  const F = (i, r, k, ph, type = "number", cls = "col-span-2") => <Input key={k} className={`${cls} h-9`} type={type} min={type === "number" ? "0" : undefined} step="any" title={ph} placeholder={ph} value={r[k] ?? ""} disabled={!write} onChange={(e) => up(i, k, e.target.value)} data-testid={`req-${k}-${i}`} />;
  return (
    <div className="space-y-2 text-sm" data-testid="product-reqs">
      <div className="hidden grid-cols-12 gap-2 px-2 text-xs text-muted-foreground md:grid"><span className="col-span-2">Type</span><span className="col-span-3">Libellé</span><span className="col-span-1">Qté</span><span className="col-span-1">Unité</span><span className="col-span-2">Calcul</span><span className="col-span-2">Détail</span><span className="col-span-1" /></div>
      {reqs.map((r, i) => (<div key={r.id || `n${i}`} className="grid grid-cols-12 items-center gap-2 rounded-xl border border-border p-2" data-testid={`req-row-${i}`}>
        <select className={`${sel} col-span-6 md:col-span-2`} value={r.type} disabled={!write} onChange={(e) => up(i, "type", e.target.value)} data-testid={`req-type-${i}`}>{Object.entries(REQ).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <Input className="col-span-6 h-9 md:col-span-3" placeholder="Libellé *" value={r.label} disabled={!write} onChange={(e) => up(i, "label", e.target.value)} data-testid={`req-label-${i}`} />
        <Input className="col-span-3 h-9 md:col-span-1" type="number" min="0" step="any" title="Quantité" value={r.quantity} disabled={!write} onChange={(e) => up(i, "quantity", e.target.value)} data-testid={`req-qty-${i}`} />
        <Input className="col-span-3 h-9 md:col-span-1" placeholder="pièce" title="Unité" value={r.unit || ""} disabled={!write} onChange={(e) => up(i, "unit", e.target.value)} data-testid={`req-unit-${i}`} />
        <select className={`${sel} col-span-6 md:col-span-2`} value={r.calc_mode} disabled={!write} onChange={(e) => up(i, "calc_mode", e.target.value)} data-testid={`req-mode-${i}`}>{Object.entries(MODES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <label className="col-span-8 flex items-center gap-1 text-xs md:col-span-2"><input type="checkbox" checked={r.mandatory !== false} disabled={!write} onChange={(e) => up(i, "mandatory", e.target.checked)} />Obligatoire</label>
        {write && <button className="col-span-4 justify-self-end md:col-span-1" aria-label="Supprimer" onClick={() => setReqs(reqs.filter((_, j) => j !== i))} data-testid={`req-del-${i}`}><Trash2 className="h-4 w-4" /></button>}
        {LINKED.includes(r.type) && <>
          <select className={`${sel} col-span-12 md:col-span-5`} value={r.linked_product_id || ""} disabled={!write} onChange={(e) => up(i, "linked_product_id", e.target.value)} data-testid={`req-linked-${i}`}><option value="">Produit lié du catalogue (optionnel)</option>{equipment.filter((x) => x.id !== item.id).map((x) => <option key={x.id} value={x.id}>{x.ref} {x.name}</option>)}</select>
          {F(i, r, "spare_qty", "Rechange (qté)")}{F(i, r, "spare_pct", "Rechange %")}</>}
        {(EXTRA[r.type] || []).map(([k, ph, t]) => F(i, r, k, ph, t || "number"))}
        {F(i, r, "note", "Note", "text", "col-span-12 md:col-span-3")}
      </div>))}
      {write && <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" onClick={() => setReqs([...reqs, { ...BLANK }])} data-testid="req-add"><Plus />Besoin</Button>
        <select className={sel} value="" onChange={(e) => { const s = equipment.find((x) => x.id === e.target.value); if (s) setReqs([...reqs, ...(s.requirements || []).map((x) => ({ ...x, id: "" }))]); }} data-testid="req-copy"><option value="">Copier les besoins de…</option>{equipment.filter((x) => x.id !== item.id && x.requirements?.length).map((x) => <option key={x.id} value={x.id}>{x.ref} {x.name}</option>)}</select>
        {tpls.length > 0 && <select className={sel} value="" onChange={(e) => { const t = tpls.find((x) => x.id === e.target.value); if (t) setReqs([...reqs, ...t.lines.map((x) => ({ ...x, id: "" }))]); }} data-testid="req-template-apply"><option value="">Appliquer un modèle…</option>{tpls.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.lines.length})</option>)}</select>}
        <Button size="sm" variant="ghost" disabled={!clean().length} onClick={() => { const name = window.prompt("Nom du modèle de besoins"); if (name?.trim()) api.post("/requirement-templates", { name: name.trim(), lines: clean() }).then(() => { toast.success("Modèle enregistré"); loadT(); }).catch(ko); }} data-testid="req-template-save">Enregistrer comme modèle</Button>
        <Button size="sm" className="ml-auto" onClick={save} data-testid="req-save">Enregistrer les besoins</Button></div>}
    </div>
  );
}

export function ProductSheetDialog({ item, equipment, onOpenChange, onSaved, write, admin, initialTab = "docs" }) {
  const [tab, setTab] = useState(initialTab);
  const { can } = useMe();
  useEffect(() => { setTab(initialTab); }, [item?.id, initialTab]);
  if (!item) return null;
  return (
    <Dialog open onOpenChange={onOpenChange}><DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto" data-testid="product-sheet">
      <DialogHeader><DialogTitle className="text-xl font-bold">{item.ref} · {item.name}</DialogTitle><DialogDescription className="sr-only">Documents et besoins du produit</DialogDescription></DialogHeader>
      <div className="flex gap-2">{[["docs", "Documents"], ["reqs", `Besoins (${(item.requirements || []).length})`], ["units", "Unités"], ["attrs", "Caractéristiques"], ...(can("finance:costs") ? [["suppliers", "Fournisseurs"]] : [])].map(([k, l]) => <button key={k} onClick={() => setTab(k)} data-testid={`product-tab-${k}`} className={`rounded-full px-4 py-1.5 text-xs font-semibold ${tab === k ? "bg-foreground text-background" : "border border-border"}`}>{l}</button>)}</div>
      {tab === "suppliers" ? <SuppliersTab key={item.id} item={item} write={write} /> : tab === "units" ? <UnitsTab key={item.id} item={item} write={write} onSaved={onSaved} /> : tab === "attrs" ? <AttrsTab key={item.id} item={item} write={write} onSaved={onSaved} /> : tab === "docs" ? <DocsTab item={item} equipment={equipment} write={write} admin={admin} onSaved={onSaved} /> : <ReqsTab key={item.id} item={item} equipment={equipment} write={write} onSaved={onSaved} />}
    </DialogContent></Dialog>
  );
}

const Totals = ({ t }) => <div className="border-t border-border pt-2 text-muted-foreground" data-testid="requirements-totals">Électricité : {t.power_w} W, {t.sockets} prise(s) · Poids : {t.weight_kg} kg · Volume : {t.volume_m3} m³ · Manutention : {t.handlers} pers. · Installation : {t.setup_min} min · Démontage : {t.teardown_min} min</div>;
const byType = (lines) => Object.keys(REQ).map((t) => [REQ[t], lines.filter((l) => l.type === t)]).filter(([, ls]) => ls.length);

export function EventRequirements({ eventId, version, checklist, write = true, onChanged }) {
  const [d, setD] = useState(null);
  const [annex, setAnnex] = useState(false);
  useEffect(() => { api.get(`/events/${eventId}/requirements`).then((r) => setD(r.data)).catch(() => {}); }, [eventId, version]);
  if (!d || !d.lines.length) return null;
  const patch = (key, ch) => api.patch(`/events/${eventId}/requirements`, { key, ...ch }).then((r) => { setD(r.data); if (!checklist) onChanged?.(); }).catch(ko);
  const groups = checklist ? [...new Set(d.lines.map((l) => l.source_product_id))].map((id) => { const ls = d.lines.filter((l) => l.source_product_id === id && l.accepted); return [`${ls[0]?.source_qty} × ${ls[0]?.source_name}`, ls]; }).filter(([, ls]) => ls.length) : byType(d.lines);
  return (
    <div className="card-soft mt-4 p-5 text-sm" data-testid="event-requirements">
      <div className="mb-2 flex flex-wrap items-center gap-3"><span className="font-semibold">{checklist ? "Check-list accessoires et consommables" : `Besoins calculés (${d.days} jour${d.days > 1 ? "s" : ""})`}</span><span className="flex-1" />
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={annex} onChange={(e) => setAnnex(e.target.checked)} data-testid="checklist-annex" />Joindre les fiches techniques</label>
        <Button size="sm" variant="outline" onClick={() => downloadPdf(`/events/${eventId}/requirements/checklist?annex=${annex}`, "check-list-preparation.pdf").catch(() => toast.error("Impossible de générer le PDF"))} data-testid="checklist-pdf"><Download />Check-list PDF</Button></div>
      {d.alerts.map((a) => <div key={a} className="mb-2 rounded-lg bg-amber-500/10 p-2 text-amber-700" data-testid="requirements-alert">{a}</div>)}
      {groups.map(([head, ls]) => (<div key={head} className="mb-2"><div className="eyebrow">{head}</div>
        {ls.map((l) => (<div key={l.key} className="flex flex-wrap items-center gap-2 py-1 pl-3" data-testid={`requirement-line-${l.requirement_id}`}>
          <span className="min-w-0 flex-1">{l.label}{!checklist && <span className="text-muted-foreground"> — {l.source_qty} × {l.source_name}</span>}{l.note && <span className="text-xs text-muted-foreground"> · {l.note}</span>}
            {!checklist && <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${l.status === "adjusted" ? "bg-amber-500/10 text-amber-700" : "bg-secondary text-muted-foreground"}`} data-testid={`requirement-status-${l.requirement_id}`}>{l.status === "adjusted" ? "ajustée" : "auto"}</span>}
            {!checklist && l.auto_added && <span className="ml-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-700" title="Ajouté automatiquement au matériel de l'événement et réservé en stock">réservé en stock</span>}</span>
          {checklist ? (<><label className="flex items-center gap-1"><input type="checkbox" checked={l.checked_out} onChange={(e) => patch(l.key, { checked_out: e.target.checked })} data-testid={`requirement-out-${l.requirement_id}`} />départ</label><label className="flex items-center gap-1"><input type="checkbox" checked={l.checked_in} onChange={(e) => patch(l.key, { checked_in: e.target.checked })} data-testid={`requirement-in-${l.requirement_id}`} />retour</label>
            {l.type === "consommable" && <Input className="h-8 w-20" type="number" min="0" title="Utilisés (décrémente le stock)" placeholder="Utilisés" defaultValue={l.used_qty} onBlur={(e) => Number(e.target.value) !== l.used_qty && patch(l.key, { used_qty: Number(e.target.value) || 0 })} data-testid={`requirement-used-${l.requirement_id}`} />}<b>{l.qty} {l.unit}</b></>)
            : l.type === "alimentation" ? <span className="text-xs text-muted-foreground">{l.voltage} {l.power_w ? `${l.power_w} W` : ""} {l.sockets ? `· ${l.sockets} prise(s)` : ""} / unité</span>
              : !["consommable", "accessoire_obligatoire", "accessoire_optionnel"].includes(l.type) ? null
                : (<>{l.type === "accessoire_optionnel" && <label className="flex items-center gap-1"><input type="checkbox" checked={l.accepted} disabled={!write} onChange={(e) => patch(l.key, { accepted: e.target.checked })} data-testid={`requirement-accept-${l.requirement_id}`} />ajouter</label>}
                  <Input className="h-8 w-20" type="number" min="0" disabled={!write} defaultValue={l.qty} key={l.qty} onBlur={(e) => Number(e.target.value) !== l.qty && patch(l.key, { adjusted_qty: Number(e.target.value) })} data-testid={`requirement-qty-${l.requirement_id}`} /><span className="w-12 text-xs text-muted-foreground">{l.unit}</span>
                  {l.status === "adjusted" && write && <button className="text-xs underline" onClick={() => patch(l.key, { adjusted_qty: -1 })} data-testid={`requirement-reset-${l.requirement_id}`}>recalculer</button>}</>)}
        </div>))}</div>))}
      {!checklist && <Totals t={d.totals} />}
    </div>
  );
}

export function QuoteMaterial({ quoteId, canEdit }) {
  const [d, setD] = useState(null);
  const [docs, setDocs] = useState([]);
  useEffect(() => { api.get(`/quotes/${quoteId}/requirements`).then((r) => setD(r.data)).catch(() => {}); api.get(`/quotes/${quoteId}/product-documents`).then((r) => setDocs(r.data)).catch(() => {}); }, [quoteId]);
  const toggle = (id, on) => { const next = docs.map((x) => (x.id === id ? { ...x, selected: on } : x)); setDocs(next); api.put(`/quotes/${quoteId}/product-documents`, { doc_ids: next.filter((x) => x.selected).map((x) => x.id) }).catch((e) => { ko(e); setDocs(docs); }); };
  if (!docs.length && !d?.lines.length) return null;
  return (
    <div className="space-y-3 rounded-2xl border border-border p-3 text-sm" data-testid="quote-material">
      {docs.length > 0 && <div data-testid="quote-share-docs"><div className="font-semibold">Fiches à joindre pour le client</div><p className="text-xs text-muted-foreground">Les fiches cochées apparaissent sur le devis en ligne et, une fois le devis envoyé, dans l'onglet Documents de l'espace client. Seuls les PDF « Partageables client » sont proposés.</p>
        {docs.map((x) => <label key={x.id} className="mt-1 flex items-center gap-2"><input type="checkbox" checked={x.selected} disabled={!canEdit} onChange={(e) => toggle(x.id, e.target.checked)} data-testid={`quote-share-doc-${x.id}`} />{x.title}<span className="text-xs text-muted-foreground">{DOC[x.type]}</span><button type="button" className="text-xs underline" onClick={() => openFile(x.file_ref)}>ouvrir</button></label>)}</div>}
      {d?.lines.length > 0 && <div data-testid="quote-requirements"><div className="font-semibold">Besoins calculés d'après les lignes enregistrées du devis (lecture seule)</div>
        {d.alerts.map((a) => <div key={a} className="mt-1 rounded-lg bg-amber-500/10 p-2 text-amber-700" data-testid="quote-requirements-alert">{a}</div>)}
        {byType(d.lines.filter((l) => l.type !== "accessoire_optionnel" || l.accepted || true)).map(([head, ls]) => <div key={head} className="mt-1"><div className="eyebrow">{head}</div>{ls.map((l) => <div key={l.key} className="flex gap-2 pl-3" data-testid={`quote-requirement-${l.requirement_id}`}><span className="flex-1">{l.label}<span className="text-muted-foreground"> — {l.source_qty} × {l.source_name}{l.type === "accessoire_optionnel" ? " (optionnel, proposé)" : ""}</span></span>{["alimentation", "logistique", "humain", "note"].includes(l.type) ? null : <b>{l.qty} {l.unit}</b>}</div>)}</div>)}
        <div className="mt-2"><Totals t={d.totals} /></div></div>}
    </div>
  );
}
