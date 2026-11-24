import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));
const MARK = { complete: "✓ complet", partial: "⚠ partiel", absent: "— absent" };
const LV = { 0: ["Mise à jour simple", "bg-secondary"], 1: ["Niveau 1 — interne", "bg-emerald-500/15 text-emerald-700"], 2: ["Niveau 2 — révision sans signature", "bg-amber-500/20 text-amber-700"], 3: ["Niveau 3 — nouvelle signature", "bg-red-500/15 text-red-700"] };
const ST = { brouillon: "Brouillon", envoye: "Envoyé", vu: "Vu", negociation: "Négociation", accepte: "Accepté" };

export function TranslationAlert({ quoteId }) {
  const [d, setD] = useState(null);
  useEffect(() => { api.get(`/quotes/${quoteId}/translation-check`).then((r) => setD(r.data)).catch(() => {}); }, [quoteId]);
  if (!d?.missing.length && !d?.warnings?.length) return null;
  if (!d.missing.length) return <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="quote-translation-alert">{d.warnings.map((w) => <div key={w}>{w}</div>)}</div>;
  return <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="quote-translation-alert">{(d.warnings || []).map((w) => <div key={w}>{w}</div>)}{d.missing.map((m) => <div key={m.equipment_id}><b>{m.name}</b> n'est pas {m.state === "partial" ? "entièrement " : ""}traduit en {d.language_label} — le client verra le repli ({m.fallback}).</div>)}<Link className="text-xs underline" to="/catalogue">Traduire maintenant dans le catalogue</Link></div>;
}

export function PackTranslations({ item, onClose }) {
  const [d, setD] = useState(null);
  const [lang, setLang] = useState("en-US");
  const [f, setF] = useState(null);
  const [fr, setFr] = useState(null);
  const [busy, setBusy] = useState(false);
  const open = useCallback((data, l) => { setD(data); setFr(data.fr); const x = data.languages.find((y) => y.code === l); setF({ name: x.name, client_description: x.client_description, notes_client: x.notes_client, labels: { ...x.labels } }); }, []);
  useEffect(() => { api.get(`/equipment/${item.id}/translations`).then((r) => open(r.data, lang)).catch(ko); }, [item.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d || !f) return null;
  const cur = d.languages.find((x) => x.code === lang);
  const save = (l, body, msg) => api.put(`/equipment/${item.id}/translations`, { lang: l, ...body }).then((r) => { open(r.data, lang); toast.success(msg); }).catch(ko);
  const ai = () => { setBusy(true); api.post(`/equipment/${item.id}/translations/ai`, { lang }).then((r) => { setF(r.data); toast.success("Brouillon généré : relisez avant d'enregistrer"); }).catch(ko).finally(() => setBusy(false)); };
  const lab = (c) => f.labels[c.equipment_id] || c.client_label;
  const area = "w-full rounded-lg border border-border bg-background p-2 text-sm";
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="pack-translations-dialog">
      <DialogHeader><DialogTitle>Traductions — {item.name} (v{d.version})</DialogTitle><DialogDescription>Le français est la langue de référence. Une traduction passe « à revoir » quand le texte français change après elle.</DialogDescription></DialogHeader>
      <div className="space-y-2 rounded-xl border border-border p-3 text-sm" data-testid="pack-fr"><b>Français — résultat promis au client</b>
        <textarea className={area} rows={2} placeholder="Ex. Sonorisation adaptée à 200 personnes, 2 micros sans fil, éclairage d'ambiance, DJ 8 h" value={fr.client_description} onChange={(e) => setFr({ ...fr, client_description: e.target.value })} data-testid="pack-fr-description" />
        <Input placeholder="Note client (facultatif)" value={fr.notes_client} onChange={(e) => setFr({ ...fr, notes_client: e.target.value })} /><Button size="sm" variant="outline" onClick={() => save("fr-FR", fr, "Texte français enregistré")} data-testid="pack-fr-save">Enregistrer le français</Button></div>
      <div className="flex flex-wrap gap-2">{d.languages.map((x) => <button key={x.code} type="button" className={`rounded-full border px-3 py-1 text-xs font-medium ${lang === x.code ? "border-primary bg-primary text-white" : "border-border"}`} onClick={() => { setLang(x.code); open(d, x.code); }} data-testid={`pack-lang-${x.code}`}>{x.label} · {MARK[x.state]}{x.stale && <span className="ml-1 rounded-full bg-orange-500 px-1.5 text-white" data-testid={`pack-stale-${x.code}`}>à revoir</span>}</button>)}</div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 text-sm"><Input placeholder={`Nom du pack (${cur.label})`} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="pack-tr-name" />
          <textarea className={area} rows={3} placeholder="Résultat promis" value={f.client_description} onChange={(e) => setF({ ...f, client_description: e.target.value })} data-testid="pack-tr-description" />
          <Input placeholder="Note client" value={f.notes_client} onChange={(e) => setF({ ...f, notes_client: e.target.value })} />
          {d.components.filter((c) => c.client_label).map((c) => <label key={c.equipment_id} className="block text-xs text-muted-foreground">{c.client_label}<Input className="mt-1 h-9" value={f.labels[c.equipment_id] || ""} onChange={(e) => setF({ ...f, labels: { ...f.labels, [c.equipment_id]: e.target.value } })} data-testid={`pack-tr-label-${c.equipment_id}`} /></label>)}
          <div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={ai} data-testid="pack-tr-ai">{busy ? "Traduction…" : "Traduire avec l'IA"}</Button><Button size="sm" disabled={!f.name.trim()} onClick={() => save(lang, f, "Traduction enregistrée")} data-testid="pack-tr-save">Enregistrer</Button></div></div>
        <div className="rounded-xl border border-border p-3 text-sm" data-testid="pack-tr-preview"><div className="mb-1 text-xs font-semibold text-muted-foreground">Ce que voit le client ({cur.label})</div><b>{f.name || item.name}</b><p className="text-muted-foreground">{f.client_description || fr.client_description}</p><ul className="mt-1 list-disc pl-5 text-muted-foreground">{d.components.map((c) => <li key={c.equipment_id}>{c.qty} × {lab(c) || "(nom de l'article)"}</li>)}</ul></div>
      </div>
    </DialogContent></Dialog>);
}

export function PackApply({ item, onClose }) {
  const [d, setD] = useState(null);
  const [pick, setPick] = useState([]);
  const [eq, setEq] = useState([]);
  const [o, setO] = useState({ past: false, overwrite: false, status: "" });
  const [res, setRes] = useState(null);
  const load = useCallback(() => api.get(`/equipment/${item.id}/pack/quotes`, { params: { past: o.past } }).then((r) => { setD(r.data); setPick([]); }).catch(ko), [item.id, o.past]);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const rows = d.quotes.filter((q) => !o.status || q.status === o.status);
  const tog = (list, set, id) => set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const apply = () => api.post(`/equipment/${item.id}/pack/apply`, { quote_ids: pick, overwrite: o.overwrite, equivalent_ids: eq, past: o.past }).then((r) => { setRes(r.data); toast.success(`${r.data.filter((x) => x.result !== "level3").length} devis mis à jour`); load(); }).catch(ko);
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="pack-apply-dialog">
      <DialogHeader><DialogTitle>Appliquer {item.name} v{d.version} aux devis</DialogTitle><DialogDescription>Le prix d'une ligne n'est jamais modifié ici. Les ajustements propres à un devis sont conservés, sauf si vous cochez « Écraser ». Les niveaux 3 demandent une V2 ou un avenant, devis par devis.</DialogDescription></DialogHeader>
      <div className="flex flex-wrap items-center gap-4 text-sm"><select className="h-9 rounded-lg border border-border bg-background px-2" value={o.status} onChange={(e) => setO({ ...o, status: e.target.value })} data-testid="pack-apply-status"><option value="">Tous statuts</option>{Object.entries(ST).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <label className="flex items-center gap-1"><input type="checkbox" checked={o.past} onChange={(e) => setO({ ...o, past: e.target.checked })} data-testid="pack-apply-past" />Inclure les événements passés</label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={o.overwrite} onChange={(e) => setO({ ...o, overwrite: e.target.checked })} data-testid="pack-apply-overwrite" />Écraser les ajustements par la composition du catalogue</label></div>
      {!rows.length && <p className="text-sm text-muted-foreground" data-testid="pack-apply-empty">Aucun devis à mettre à jour.</p>}
      <div className="divide-y divide-border">{rows.map((q) => (
        <div key={q.id} className="py-2 text-sm" data-testid={`pack-apply-row-${q.number}`}><div className="flex flex-wrap items-center gap-2"><input type="checkbox" disabled={q.level === 3 && !(q.needs_equivalent && eq.includes(q.id))} checked={pick.includes(q.id)} onChange={() => tog(pick, setPick, q.id)} data-testid={`pack-apply-pick-${q.number}`} /><b>{q.number}</b><span>{q.client}</span><span className="text-xs text-muted-foreground">{q.event_date ? q.event_date.split("-").reverse().join("/") : "date à définir"} · {ST[q.status]}</span>
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${LV[q.level][1]}`} data-testid={`pack-apply-level-${q.number}`}>{LV[q.level][0]}</span>{q.kept_adjustments > 0 && !o.overwrite && <span className="text-xs text-amber-600">{q.kept_adjustments} ajustement(s) conservé(s)</span>}</div>
          {q.diff.map((x, i) => <div key={i} className="pl-6 text-xs text-muted-foreground">{x.text}</div>)}
          {q.needs_equivalent && <label className="flex items-center gap-1 pl-6 text-xs"><input type="checkbox" checked={eq.includes(q.id)} onChange={() => tog(eq, setEq, q.id)} data-testid={`pack-apply-equivalent-${q.number}`} />Équivalent ou supérieur (sinon nouvelle signature)</label>}</div>))}</div>
      {res && <div className="rounded-xl bg-secondary/50 p-3 text-xs" data-testid="pack-apply-result">{res.map((x) => <div key={x.id}>{x.number} : {x.result === "level3" ? "niveau 3 — non appliqué, ouvrez le devis pour créer une V2 ou un avenant" : x.result === "updated" ? `mis à jour${x.resend ? " (déjà envoyé : pensez à le renvoyer)" : ""}` : x.level === 2 ? `révision ${x.revision} générée, client notifié en production` : "mis à jour en interne, sans notification"}</div>)}</div>}
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Fermer</Button><Button disabled={!pick.length} onClick={apply} data-testid="pack-apply-confirm">Appliquer à {pick.length} devis</Button></div>
    </DialogContent></Dialog>);
}
