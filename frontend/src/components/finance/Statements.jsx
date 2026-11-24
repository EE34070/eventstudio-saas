import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e), { duration: 10000 });
const fr = (d) => (d || "").split("-").reverse().join("/");
const fmt = (x, u = "€") => (x === null || x === undefined ? "—" : u === "€" ? `${Math.round(x).toLocaleString("fr-FR")} €` : `${x.toLocaleString("fr-FR")} ${u}`);
const dl = (path, name) => api.get(path, { responseType: "blob" }).then((r) => { const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = name; a.click(); }).catch(ko);

function Draft({ d, keys, sources, onDone }) {
  const [h, setH] = useState(d.headings);
  const [cur, setCur] = useState(d);
  const [ok, setOk] = useState([]);
  const [pdf, setPdf] = useState("");
  useEffect(() => { if (d.file_id) api.get(`/files/${d.file_id}`, { responseType: "blob" }).then((r) => setPdf(URL.createObjectURL(r.data))).catch(() => {}); }, [d.file_id]);
  const save = () => api.put(`/finance/statements/${d.id}`, { start: cur.start, end: cur.end, headings: h }).then((r) => { setCur(r.data); setH(r.data.headings); toast.success("Montants enregistrés, contrôles relancés"); return r.data; }).catch(ko);
  const validate = async () => { if (cur.editable && !(await save())) return; api.post(`/finance/statements/${d.id}/validate`, { confirmed: ok }).then(() => { toast.success("Exercice validé et verrouillé"); onDone(); }).catch(ko); };
  const doubt = (k) => (cur.confidence[k] ?? 1) < 0.8 && !ok.includes(k);
  const groups = [...new Set(keys.map((k) => k.group))];
  const blocked = cur.controls.some((c) => c.level === "block");
  return (
    <div className="rounded-2xl border border-amber-500/60 p-4" data-testid={`statement-draft-${d.end}`}>
      <div className="flex flex-wrap items-center gap-2"><b>Brouillon — exercice du {fr(cur.start)} au {fr(cur.end)}</b><span className="rounded-full bg-secondary px-2 py-0.5 text-xs">{sources[d.source]} · v{d.version}</span><span className="text-xs text-muted-foreground">{d.filename}{d.accounts ? ` · ${d.accounts} comptes` : ""}</span><span className="flex-1" />
        <Button size="sm" variant="ghost" onClick={() => api.delete(`/finance/statements/${d.id}`).then(onDone).catch(ko)} data-testid="statement-draft-delete">Supprimer</Button>
        {cur.editable && <Button size="sm" variant="outline" onClick={save} data-testid="statement-draft-save">Enregistrer et recontrôler</Button>}
        <Button size="sm" disabled={blocked && !cur.editable} onClick={validate} data-testid="statement-draft-validate">Valider et verrouiller</Button></div>
      {[...cur.warnings.map((t) => ({ level: "warn", text: t })), ...cur.controls].map((c, i) => <p key={i} className={`mt-2 rounded-lg p-2 text-sm ${c.level === "block" ? "bg-red-500/10 font-semibold text-red-700" : "bg-amber-500/10 text-amber-800"}`} data-testid={`statement-control-${c.level}`}>{c.level === "block" ? "Bloquant : " : ""}{c.text}</p>)}
      {!cur.controls.some((c) => c.level === "block") && <p className="mt-2 text-sm text-emerald-700" data-testid="statement-balanced">Bilan équilibré : total actif = total passif = {fmt(cur.values.total_actif)} · résultat {fmt(cur.values.net)}</p>}
      {cur.editable && <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div className="space-y-3"><div className="flex gap-2 text-xs"><label>Début<Input type="date" className="h-8" value={cur.start} onChange={(e) => setCur({ ...cur, start: e.target.value })} /></label><label>Fin<Input type="date" className="h-8" value={cur.end} onChange={(e) => setCur({ ...cur, end: e.target.value })} /></label></div>
          <p className="text-xs text-muted-foreground">Montants lus par IA. En orange : lecture douteuse, à confirmer ou corriger avant validation.</p>
          {groups.map((g) => <div key={g}><div className="eyebrow">{g}</div>{keys.filter((k) => k.group === g).map((k) => (
            <div key={k.key} className={`flex items-center gap-2 py-0.5 text-sm ${doubt(k.key) ? "rounded bg-orange-500/20 px-1" : ""}`} data-testid={`statement-field-${k.key}`} data-doubt={doubt(k.key)}><span className="min-w-0 flex-1 truncate">{k.label}</span>
              {(cur.confidence[k.key] ?? 1) < 0.8 && <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={ok.includes(k.key)} onChange={(e) => setOk(e.target.checked ? [...ok, k.key] : ok.filter((x) => x !== k.key))} data-testid={`statement-confirm-${k.key}`} />vérifié</label>}
              <Input type="number" step="0.01" className="h-8 w-36 text-right" value={h[k.key] ?? 0} onChange={(e) => setH({ ...h, [k.key]: e.target.value === "" ? 0 : Number(e.target.value) })} data-testid={`statement-input-${k.key}`} /></div>))}</div>)}</div>
        {pdf ? <iframe title="Document importé" src={pdf} className="h-[80vh] w-full rounded-xl border border-border" data-testid="statement-pdf" /> : <p className="text-sm text-muted-foreground">Document non affichable.</p>}
      </div>}
    </div>);
}

function MapDialog({ onClose }) {
  const [d, setD] = useState(null);
  const [f, setF] = useState({ prefix: "", heading: "" });
  useEffect(() => { api.get("/finance/heading-map").then((r) => setD(r.data)).catch(ko); }, []);
  if (!d) return null;
  const put = (body) => api.put("/finance/heading-map", body).then((r) => { setD(r.data); toast.success("Correspondance enregistrée ; les brouillons sont reclassés"); }).catch(ko);
  const lab = (h) => h.split("|").map((x) => d.headings.find((y) => y.key === x)?.label || x).join(" / si créditeur : ");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid="heading-map-dialog">
      <DialogHeader><DialogTitle>Table de correspondance des comptes</DialogTitle><DialogDescription>Chaque compte est classé par le préfixe le plus long qui lui correspond. Vos règles passent avant le classement par défaut. Les exercices déjà validés ne sont pas reclassés.</DialogDescription></DialogHeader>
      <div className="flex flex-wrap gap-2"><Input className="w-32" placeholder="Compte (ex. 6226)" value={f.prefix} onChange={(e) => setF({ ...f, prefix: e.target.value.replace(/\D/g, "") })} data-testid="map-prefix" />
        <select className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-background px-2 text-sm" value={f.heading} onChange={(e) => setF({ ...f, heading: e.target.value })} data-testid="map-heading"><option value="">Rubrique…</option>{d.headings.map((h) => <option key={h.key} value={h.key}>{h.label}</option>)}</select>
        <Button disabled={!f.prefix || !f.heading} onClick={() => put(f)} data-testid="map-save">Ajouter</Button></div>
      {d.custom.length > 0 && <div className="text-sm"><b>Vos règles</b>{d.custom.map((m) => <div key={m.prefix} className="flex items-center gap-2" data-testid={`map-custom-${m.prefix}`}><span className="w-20 font-mono">{m.prefix}</span><span className="flex-1">{lab(m.heading)}</span><button className="text-xs underline" onClick={() => put({ prefix: m.prefix, heading: "" })}>retirer</button></div>)}</div>}
      <details className="text-sm"><summary className="cursor-pointer font-semibold">Classement par défaut (plan comptable général)</summary>{d.default.map((m) => <div key={m.prefix} className="flex gap-2 text-xs"><span className="w-20 font-mono">{m.prefix}</span><span>{lab(m.heading)}</span></div>)}</details>
    </DialogContent></Dialog>);
}

export function StatementsTab() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState("");
  const [period, setPeriod] = useState({ start: "", end: "" });
  const [map, setMap] = useState(false);
  const pick = useRef({});
  const load = useCallback(() => api.get("/finance/statements").then((r) => setD(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const up = (kind) => (e) => { const x = e.target.files[0]; e.target.value = ""; if (!x) return; const fd = new FormData(); fd.append("file", x);
    if (kind === "balance") { if (!period.start || !period.end) return toast.error("Indiquez d'abord le début et la fin de l'exercice de cette balance"); fd.append("start", period.start); fd.append("end", period.end); }
    if (kind === "liasse" || kind === "plaquette") { fd.append("kind", kind); fd.append("start", period.start); fd.append("end", period.end); }
    setBusy(kind); api.post(`/finance/statements/import/${kind === "fec" || kind === "balance" ? kind : "pdf"}`, fd, { timeout: 180000 }).then(() => { toast.success("Import terminé : vérifiez le brouillon puis validez"); load(); }).catch(ko).finally(() => setBusy("")); };
  const ys = [...d.years].reverse().slice(-5);
  const SRC = [["fec", "FEC (.txt / .csv)", ".txt,.csv"], ["balance", "Balance (Excel / CSV)", ".xlsx,.csv,.txt"], ["liasse", "Liasse fiscale PDF (IA)", "application/pdf"], ["plaquette", "Plaquette PDF (IA)", "application/pdf"]];
  return (
    <div className="space-y-4" data-testid="statements-tab">
      {d.can_manage && <div className="rounded-2xl border border-border p-4" data-testid="statements-import"><b>Importer un exercice</b>
        <p className="text-xs text-muted-foreground">Par ordre de fiabilité : Pennylane ({d.pennylane_connected ? "connecté" : "non connecté pour l'instant"}), FEC, liasse fiscale, plaquette, balance. Rien n'est enregistré comme exercice sans votre validation. L'app n'écrit aucune écriture comptable.</p>
        <div className="mt-2 flex flex-wrap items-end gap-2">{SRC.map(([k, l, acc]) => <span key={k}><input ref={(el) => { pick.current[k] = el; }} type="file" accept={acc} className="hidden" onChange={up(k)} data-testid={`statements-file-${k}`} /><Button size="sm" variant="outline" disabled={!!busy} onClick={() => pick.current[k].click()} data-testid={`statements-import-${k}`}>{busy === k ? "Lecture en cours…" : l}</Button></span>)}
          <label className="text-xs text-muted-foreground">Début d'exercice<Input type="date" className="h-8" value={period.start} onChange={(e) => setPeriod({ ...period, start: e.target.value })} data-testid="statements-start" /></label>
          <label className="text-xs text-muted-foreground">Fin d'exercice<Input type="date" className="h-8" value={period.end} onChange={(e) => setPeriod({ ...period, end: e.target.value })} data-testid="statements-end" /></label>
          <span className="text-xs text-muted-foreground">Dates obligatoires pour une balance ; pour un FEC ou un PDF elles sont lues dans le fichier.</span>
          <span className="flex-1" /><Button size="sm" variant="ghost" onClick={() => setMap(true)} data-testid="statements-map-open">Table de correspondance</Button></div></div>}
      {d.drafts.map((x) => <Draft key={x.id} d={x} keys={d.editable_keys} sources={d.sources} onDone={load} />)}
      {!ys.length ? <p className="rounded-2xl border border-dashed border-border p-6 text-sm text-muted-foreground" data-testid="statements-empty">Aucun exercice validé pour l'instant. Importez un FEC, une balance, une liasse ou une plaquette.</p> : <>
        <div className="flex flex-wrap items-center gap-2 text-sm"><b>{ys.length} exercice(s) validé(s)</b>{ys.map((y) => <span key={y.id} className="rounded-full bg-secondary px-2 py-0.5 text-xs" data-testid={`statement-year-${y.end}`}>{y.end.slice(0, 4)} · {d.sources[y.source]} · v{y.version} · verrouillé</span>)}<span className="flex-1" />
          <Button size="sm" variant="outline" onClick={() => dl("/finance/statements/export.xlsx", "etats-financiers.xlsx")} data-testid="statements-export-xlsx">Excel</Button><Button size="sm" variant="outline" onClick={() => dl("/finance/statements/export.pdf", "etats-financiers.pdf")} data-testid="statements-export-pdf">PDF</Button></div>
        {d.layout.map((s) => <div key={s.id} className="overflow-x-auto rounded-2xl border border-border p-4" data-testid={`statements-${s.id}`}><table className="w-full text-sm"><thead><tr className="border-b border-border text-xs text-muted-foreground"><th className="py-2 text-left text-sm text-foreground">{s.title}</th>{ys.map((y, i) => <th key={y.id} className="whitespace-nowrap px-2 text-right" colSpan={i ? 2 : 1}>Clos le {fr(y.end)}</th>)}</tr></thead>
          <tbody>{s.rows.map((r) => <tr key={r.key} className={`border-b border-border/50 ${r.total ? "font-semibold" : ""}`} data-testid={`row-${s.id}-${r.key}`}><td className="py-1">{r.label}</td>{ys.map((y, i) => { const v = y.values[r.key], p = i ? ys[i - 1].values[r.key] : null; const dv = i && v != null && p != null ? v - p : null;
            return [<td key={y.id} className="whitespace-nowrap px-2 text-right">{fmt(v, r.unit)}</td>, i ? <td key={`${y.id}v`} className={`whitespace-nowrap px-2 text-right text-xs ${dv < 0 ? "text-red-600" : "text-emerald-700"}`}>{dv == null ? "" : `${dv >= 0 ? "+" : ""}${fmt(dv, r.unit)}${(r.unit || "€") === "€" && p ? ` (${dv >= 0 ? "+" : ""}${((dv / Math.abs(p)) * 100).toFixed(1)} %)` : ""}`}</td> : null]; })}</tr>)}</tbody></table></div>)}
        <div className="rounded-2xl border border-border p-4 text-sm" data-testid="statements-reading"><b>Lecture en clair</b> <span className="text-xs text-muted-foreground">{d.note}</span>{ys.map((y) => <div key={y.id} className="mt-2"><div className="font-semibold">Exercice clos le {fr(y.end)}</div>{y.reading.map((t) => <p key={t}>{t}</p>)}{y.controls.map((c) => <p key={c.text} className="text-amber-700">{c.text}</p>)}</div>)}</div></>}
      {map && <MapDialog onClose={() => { setMap(false); load(); }} />}
    </div>);
}
