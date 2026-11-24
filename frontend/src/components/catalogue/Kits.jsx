import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Section } from "@/components/common";
import { api, errMsg, downloadPdf } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const COLORS = ["#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#e0e7ff"];
const SIDES = [["face", "Face"], ["gauche", "Gauche"], ["droite", "Droite"], ["arriere", "Arrière"]];
const Lab = ({ label, children }) => <label className="block text-xs text-muted-foreground">{label}<div className="mt-1">{children}</div></label>;

export function Plan({ layout }) {
  if (!layout) return null;
  const formats = [...new Set(layout.pieces.map((p) => p.format))];
  const k = 40;
  return (
    <svg viewBox={`-4 -4 ${layout.w * k + 8} ${layout.d * k + 24}`} className="max-h-80 w-full rounded-xl border border-border bg-card" data-testid="kit-plan">
      {layout.pieces.map((p) => <g key={p.n}><rect x={p.x * k} y={p.y * k} width={p.w * k} height={p.d * k} fill={p.missing ? "#fecaca" : COLORS[formats.indexOf(p.format) % COLORS.length]} stroke="#475569" strokeWidth="1" strokeDasharray={p.missing ? "4 3" : ""} /><text x={(p.x + p.w / 2) * k} y={(p.y + p.d / 2) * k + 4} textAnchor="middle" fontSize="11">{p.n}</text></g>)}
      <text x={(layout.w * k) / 2} y={layout.d * k + 16} textAnchor="middle" fontSize="11" fill="#64748b">Public — {layout.w} × {layout.d} m{layout.carpet ? ` — moquette : ${layout.carpet.les} lés de ${layout.carpet.longueur_le} m, sens ${layout.carpet.sens}, chute ${layout.carpet.chute} m²` : ""}</text>
    </svg>
  );
}

const Lines = ({ lines, onAdjust }) => (
  <div className="space-y-1 text-sm" data-testid="kit-lines">{lines.map((l) => (
    <div key={l.product_id} className="flex flex-wrap items-center gap-2 border-b border-border py-1 last:border-0" data-testid={`kit-line-${l.product_id}`}>
      <span className="min-w-0 flex-1">{l.ref} {l.name}{l.note ? <span className="text-xs text-muted-foreground"> · {l.note}</span> : null}{l.adjusted_qty != null && <span className="ml-2 rounded-full bg-amber-500/10 px-2 text-xs text-amber-700">ajustée</span>}</span>
      {l.missing > 0 && <span className="rounded-full bg-red-500/10 px-2 text-xs font-semibold text-red-700" data-testid={`kit-missing-${l.product_id}`}>manque {l.missing}</span>}
      {l.available != null && <span className="text-xs text-muted-foreground">{l.available} dispo</span>}
      {onAdjust ? <><Input type="number" min="0" step="any" className="h-8 w-20" defaultValue={l.qty} key={l.qty} onBlur={(e) => Number(e.target.value) !== l.qty && onAdjust(l.product_id, Number(e.target.value))} data-testid={`kit-qty-${l.product_id}`} />{l.adjusted_qty != null && <button className="text-xs underline" onClick={() => onAdjust(l.product_id, -1)}>recalculer</button>}</> : <b data-testid={`kit-qty-${l.product_id}`}>{l.qty}</b>}
    </div>))}</div>
);

function Wizard({ ev, kits, defaults, initial, onClose, onDone }) {
  const [kit, setKit] = useState(initial?.kit_id || "scene");
  const [p, setP] = useState({ ...defaults, ouverture: "", profondeur: "", surface_cible: "", ...(initial?.params || {}) });
  const [res, setRes] = useState(null);
  const set = (k, v) => { setP((x) => ({ ...x, [k]: v })); setRes(null); };
  const N = (k) => (p[k] === "" || p[k] == null ? null : Number(p[k]));
  const params = { ...p, ouverture: N("ouverture"), profondeur: N("profondeur"), surface_cible: N("surface_cible"), hauteur: N("hauteur") ?? 0, pieds_par_praticable: N("pieds_par_praticable") ?? 4, nb_escaliers: N("nb_escaliers") ?? 1, longueur_garde_corps: N("longueur_garde_corps") ?? 0 };
  const compute = (extra = {}) => api.post(`/events/${ev.id}/kits/compute`, { kit_id: kit, params: { ...params, ...extra } }).then((r) => { setRes(r.data); if (extra.ouverture) setP((x) => ({ ...x, ...extra })); }).catch(ko);
  const apply = () => (initial ? api.patch(`/events/${ev.id}/kits/${initial.id}`, { params }) : api.post(`/events/${ev.id}/kits`, { kit_id: kit, params })).then(() => { toast.success("Composants ajoutés au matériel de l'événement"); onDone(); }).catch(ko);
  const num = (k, label, tid) => <Lab label={label}><Input type="number" min="0" step="any" value={p[k] ?? ""} onChange={(e) => set(k, e.target.value)} data-testid={tid} /></Lab>;
  const chk = (k, label, tid) => <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={!!p[k]} onChange={(e) => set(k, e.target.checked)} data-testid={tid} />{label}</label>;
  return (
    <Dialog open onOpenChange={onClose}><DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto" data-testid="kit-wizard">
      <DialogHeader><DialogTitle>{initial ? "Modifier la scène" : "Ajouter une scène / un article composé"}</DialogTitle><DialogDescription>1. Paramètres · 2. Dimensions et plan · 3. Composants calculés avec le stock aux dates de l'événement.</DialogDescription></DialogHeader>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Lab label="Nomenclature"><select className={`${sel} w-full`} disabled={!!initial} value={kit} onChange={(e) => { setKit(e.target.value); setRes(null); }} data-testid="kit-select">{kits.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}</select></Lab>
        {num("surface_cible", "Surface cible (m²)", "kit-surface")}{num("ouverture", "Ouverture (m)", "kit-width")}{num("profondeur", "Profondeur (m)", "kit-depth")}
        {num("hauteur", "Hauteur (cm)", "kit-height")}<Lab label="Système / gamme"><Input value={p.systeme || ""} onChange={(e) => set("systeme", e.target.value)} data-testid="kit-system" /></Lab>
        {num("pieds_par_praticable", "Pieds par praticable", "kit-legs")}<Lab label="Couleur de moquette"><Input value={p.couleur_moquette || ""} onChange={(e) => set("couleur_moquette", e.target.value)} data-testid="kit-carpet-color" /></Lab>
      </div>
      <div className="flex flex-wrap items-center gap-4">{chk("moquette", "Moquette", "kit-carpet")}{chk("jupe", "Jupe", "kit-skirt")}
        {p.jupe && SIDES.map(([k, l]) => <label key={k} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={(p.cotes_jupe || []).includes(k)} onChange={(e) => set("cotes_jupe", e.target.checked ? [...(p.cotes_jupe || []), k] : p.cotes_jupe.filter((x) => x !== k))} />{l}</label>)}
        {chk("escalier", "Escalier", "kit-stairs")}{chk("garde_corps", "Garde-corps", "kit-rail")}{chk("terrain_irregulier", "Terrain irrégulier", "kit-uneven")}
        <Button size="sm" className="ml-auto" onClick={() => compute()} data-testid="kit-compute">Calculer</Button></div>
      {res && <div className="space-y-3" data-testid="kit-result">
        <div className="font-semibold" data-testid="kit-label">{res.label}</div>
        {res.proposals.length > 0 && <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="kit-proposals">Dimensions proposées :{res.proposals.map((o) => <Button key={`${o.ouverture}x${o.profondeur}`} size="sm" variant="outline" onClick={() => compute({ ouverture: o.ouverture, profondeur: o.profondeur })}>{o.ouverture} × {o.profondeur} m ({o.surface} m²)</Button>)}</div>}
        {[...res.alerts, ...res.errors].map((a) => <p key={a} className="rounded-lg bg-amber-500/10 p-2 text-sm text-amber-700" data-testid="kit-alert">{a}</p>)}
        <Plan layout={res.layout} /><Lines lines={res.lines} />
        <Button onClick={apply} data-testid="kit-apply">{initial ? "Recalculer et enregistrer" : "Ajouter à l'événement"}</Button></div>}
    </DialogContent></Dialog>
  );
}

export function KitEditor({ open, onOpenChange }) {
  const [list, setList] = useState([]);
  const [k, setK] = useState(null);
  const [test, setTest] = useState({});
  const load = useCallback(() => api.get("/kits").then((r) => setList(r.data.kits)).catch(ko), []);
  useEffect(() => { if (open) { load(); setK(null); } }, [open, load]);
  const up = (i, key, v) => setK({ ...k, lines: k.lines.map((x, j) => (j === i ? { ...x, [key]: v } : x)) });
  const VARS = { surface: 50, ouverture: 10, profondeur: 5, perimetre: 30, hauteur: 60, nb_praticables: 25, nb_pieds: 100, longueur_jonctions: 45, joints_moquette: 20, ml_moquette: 26, longueur_jupe: 20, nb_escaliers: 1, longueur_garde_corps: 4, clamps_par_metre: 1, moquette: true, jupe: true, escalier: false, garde_corps: false, terrain_irregulier: false };
  const run = (i, f) => api.post("/kits/test-formula", { formula: f, variables: VARS }).then((r) => setTest({ ...test, [i]: r.data.ok ? `= ${r.data.result}` : r.data.error })).catch(ko);
  const save = () => api.put(`/kits/${k.id}`, { name: k.name, tile_role: k.tile_role, use_legs: k.use_legs, lines: k.lines.filter((x) => x.qty) }).then((r) => { setList(r.data.kits); setK(null); toast.success("Nomenclature enregistrée"); }).catch(ko);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto" data-testid="kit-editor">
      <DialogHeader><DialogTitle>Nomenclatures</DialogTitle><DialogDescription>Un composant est choisi par son rôle (caractéristique « Rôle » du produit). Quantité et condition sont des formules ; « Tester » les évalue sur une scène 10 × 5 m.</DialogDescription></DialogHeader>
      {!k ? <div className="space-y-2 text-sm">{list.map((x) => <div key={x.id} className="flex items-center gap-2 rounded-xl border border-border p-3" data-testid={`kit-${x.id}`}><b>{x.name}</b><span className="text-xs text-muted-foreground">{x.lines.length} composants{x.custom ? " · personnalisée" : " · par défaut"}</span><span className="flex-1" />
        {x.custom && <button className="text-xs underline" onClick={() => window.confirm("Supprimer cette nomenclature personnalisée (ou revenir à celle par défaut) ?") && api.delete(`/kits/${x.id}`).then((r) => setList(r.data.kits)).catch(ko)}>Réinitialiser</button>}
        <Button size="sm" variant="outline" onClick={() => { setK({ ...x, lines: x.lines.map((y) => ({ ...y })) }); setTest({}); }} data-testid={`kit-edit-${x.id}`}>Modifier</Button></div>)}
        <Button size="sm" onClick={() => { setK({ id: "new", name: "", tile_role: "praticable", use_legs: false, lines: [] }); setTest({}); }} data-testid="kit-new"><Plus />Nouvelle nomenclature</Button></div>
        : <div className="space-y-2 text-sm">
          <div className="grid grid-cols-3 gap-2"><Input placeholder="Nom *" value={k.name} onChange={(e) => setK({ ...k, name: e.target.value })} data-testid="kit-name" /><Input placeholder="Rôle des modules (praticable, dalle…)" value={k.tile_role} onChange={(e) => setK({ ...k, tile_role: e.target.value })} data-testid="kit-tile-role" /><label className="flex items-center gap-1"><input type="checkbox" checked={k.use_legs} onChange={(e) => setK({ ...k, use_legs: e.target.checked })} />Avec pieds</label></div>
          {k.lines.map((x, i) => <div key={i} className="grid grid-cols-12 items-center gap-2" data-testid={`kit-row-${i}`}><Input className="col-span-2 h-9" placeholder="Rôle" value={x.role} onChange={(e) => up(i, "role", e.target.value)} /><Input className="col-span-2 h-9" placeholder="Libellé" value={x.label} onChange={(e) => up(i, "label", e.target.value)} />
            <Input className="col-span-3 h-9 font-mono text-xs" placeholder="Quantité (formule)" value={x.qty} onChange={(e) => up(i, "qty", e.target.value)} data-testid={`kit-row-qty-${i}`} /><Input className="col-span-2 h-9 font-mono text-xs" placeholder="Condition" value={x.cond || ""} onChange={(e) => up(i, "cond", e.target.value)} />
            <button className="col-span-1 text-xs underline" onClick={() => run(i, x.qty)} data-testid={`kit-row-test-${i}`}>Tester</button><span className="col-span-1 truncate text-xs" title={test[i]} data-testid={`kit-row-result-${i}`}>{test[i]}</span>
            <button className="col-span-1" aria-label="Supprimer" onClick={() => setK({ ...k, lines: k.lines.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button></div>)}
          <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setK({ ...k, lines: [...k.lines, { role: "", label: "", qty: "1", cond: "" }] })} data-testid="kit-add-row"><Plus />Composant</Button><span className="flex-1" /><Button size="sm" variant="ghost" onClick={() => setK(null)}>Annuler</Button><Button size="sm" disabled={!k.name.trim()} onClick={save} data-testid="kit-save">Enregistrer</Button></div>
        </div>}
    </DialogContent></Dialog>
  );
}

export function EventKits({ ev, write, onChanged }) {
  const [meta, setMeta] = useState({ kits: [], default_params: {} });
  const [wiz, setWiz] = useState(null);
  useEffect(() => { api.get("/kits").then((r) => setMeta(r.data)).catch(() => {}); }, []);
  const rows = ev.kit_instances || [];
  const done = () => { setWiz(null); onChanged(); };
  return (
    <Section title="Scènes et articles composés" testid="kits-section" actions={write && <Button size="sm" variant="outline" onClick={() => setWiz({})} data-testid="kit-add"><Plus />Ajouter une scène</Button>}>
      {!rows.length && <p className="text-sm text-muted-foreground">Aucune scène. Les composants calculés sont réservés en stock et les manques apparaissent dans le bloc « Manques ».</p>}
      {rows.map((k) => (<div key={k.id} className="mb-4 space-y-2" data-testid={`kit-instance-${k.id}`}>
        <div className="flex flex-wrap items-center gap-2"><b data-testid={`kit-instance-label-${k.id}`}>{k.label}</b><span className="flex-1" />
          <Button size="sm" variant="ghost" onClick={() => downloadPdf(`/events/${ev.id}/kits/${k.id}/plan`, "plan-scene.pdf").catch(() => toast.error("Impossible de générer le plan"))} data-testid={`kit-plan-pdf-${k.id}`}><Download />Plan PDF</Button>
          {write && <><Button size="sm" variant="outline" onClick={() => setWiz(k)} data-testid={`kit-edit-instance-${k.id}`}>Modifier</Button><button aria-label="Supprimer" onClick={() => window.confirm("Retirer cette scène et ses composants de l'événement ?") && api.delete(`/events/${ev.id}/kits/${k.id}`).then(onChanged).catch(ko)} data-testid={`kit-delete-${k.id}`}><Trash2 className="h-4 w-4" /></button></>}</div>
        {(k.alerts || []).map((a) => <p key={a} className="rounded-lg bg-amber-500/10 p-2 text-sm text-amber-700">{a}</p>)}
        <Plan layout={k.layout} />
        <Lines lines={k.lines} onAdjust={write ? (pid, q) => api.patch(`/events/${ev.id}/kits/${k.id}`, { product_id: pid, adjusted_qty: q }).then(onChanged).catch(ko) : null} />
      </div>))}
      {wiz && <Wizard ev={ev} kits={meta.kits} defaults={meta.default_params} initial={wiz.id ? wiz : null} onClose={() => setWiz(null)} onDone={done} />}
    </Section>
  );
}
