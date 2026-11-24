import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Lock, Plus, Trash2, Unlock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, downloadPdf, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";
import { RoadmapSend } from "@/components/events/RoadmapSend";

const ko = (e) => toast.error(errMsg(e));
const SRC = { organizer: ["Organisateur", "bg-sky-500/15 text-sky-700"], internal: ["Exclusivity", "bg-secondary"], auto: ["Auto", "bg-amber-500/20 text-amber-700"] };
const PHASE = { installation: "border-l-emerald-500", exploitation: "border-l-violet-500", dismantling: "border-l-orange-500", organizer: "border-l-sky-500" };
const REL = { concerns_us: "Nous concerne", not_concerned: "Ne nous concerne pas", to_check: "À vérifier" };
const hm = (s) => s.slice(11, 16);
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));

function Review({ src, onClose, onValidate }) {
  const [rows, setRows] = useState(src.raw_extraction);
  const up = (i, patch) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="schedule-review">
      <DialogHeader><DialogTitle>Vérifier le planning importé (V{src.version})</DialogTitle><DialogDescription>{src.filename} — {rows.length} étape(s) lue(s). Rien n'est enregistré avant « Valider l'import ». Les champs peu sûrs sont en orange.{src.warning ? ` ${src.warning}` : ""}</DialogDescription></DialogHeader>
      <div className="divide-y divide-border">{rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2 py-1.5 text-sm" data-testid={`review-row-${i}`}>
          <Input className={`h-8 w-44 ${r.unsure ? "border-amber-500 bg-amber-500/10" : ""}`} type="datetime-local" value={r.start} onChange={(e) => up(i, { start: e.target.value })} />
          <Input className="h-8 w-16" type="number" min="0" value={r.duration_min} onChange={(e) => up(i, { duration_min: Number(e.target.value) || 0 })} aria-label="Durée (min)" />
          <Input className="h-8 min-w-40 flex-1" value={r.title} onChange={(e) => up(i, { title: e.target.value })} />
          <span className="w-28 truncate text-xs text-muted-foreground">{r.space_label}</span>
          <select className="h-8 rounded-lg border border-border bg-background px-1 text-xs" value={r.relevance} onChange={(e) => up(i, { relevance: e.target.value })} data-testid={`review-relevance-${i}`}>{Object.entries(REL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <button type="button" aria-label="Retirer" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
        </div>))}</div>
      <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Annuler</Button><Button disabled={!rows.length || rows.some((r) => !r.title || !r.start)} onClick={() => onValidate(rows)} data-testid="schedule-validate">Valider l'import</Button></div>
    </DialogContent></Dialog>);
}

function PlanViewer({ plan, write, onClose, onSaved }) {
  const [page, setPage] = useState(0);
  const [url, setUrl] = useState("");
  const [anns, setAnns] = useState(plan.annotations || []);
  const [tool, setTool] = useState("pin");
  const [text, setText] = useState("");
  const [vis, setVis] = useState("internal");
  const [showInternal, setShowInternal] = useState(true);
  const [first, setFirst] = useState(null);
  const box = useRef(null);
  useEffect(() => { let u; api.get(`/organizer-plans/${plan.id}/page/${page}`, { responseType: "blob" }).then((r) => { u = URL.createObjectURL(r.data); setUrl(u); }).catch(ko); return () => u && URL.revokeObjectURL(u); }, [plan.id, page]);
  const click = (e) => {
    if (!write) return;
    const r = box.current.getBoundingClientRect(); const p = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
    const mk = (geometry) => { setAnns([...anns, { id: uid(), page, type: tool, geometry, text, layer: "", visibility: vis, status: "open" }]); setFirst(null); };
    if (tool === "pin" || tool === "text") mk(p); else if (!first) setFirst(p); else mk({ x1: first.x, y1: first.y, x2: p.x, y2: p.y });
  };
  const save = () => api.put(`/organizer-plans/${plan.id}/annotations`, { annotations: anns }).then(() => { toast.success("Annotations enregistrées (le fichier d'origine n'est pas modifié)"); onSaved(); }).catch(ko);
  const shown = anns.filter((a) => a.page === page && (showInternal || a.visibility === "shared"));
  const pins = anns.filter((a) => a.type === "pin");
  const col = (a) => (a.visibility === "shared" ? "#0284c7" : "#dc2626");
  const pill = (on) => `h-8 rounded-full border px-3 text-xs font-medium ${on ? "border-primary bg-primary text-white" : "border-border"}`;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}><DialogContent className="max-h-[95vh] max-w-6xl overflow-y-auto" data-testid="plan-viewer">
      <DialogHeader><DialogTitle>{plan.filename} — V{plan.version}</DialogTitle><DialogDescription>Cliquez sur le plan pour annoter (flèche et rectangle : deux clics). Rouge = interne, bleu = partagé avec l'organisateur.</DialogDescription></DialogHeader>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {write && <>{[["pin", "Pastille"], ["arrow", "Flèche"], ["rect", "Rectangle"], ["text", "Texte"]].map(([k, l]) => <button key={k} type="button" className={pill(tool === k)} onClick={() => { setTool(k); setFirst(null); }} data-testid={`plan-tool-${k}`}>{l}</button>)}
          <Input className="h-8 w-52" placeholder="Note / texte" value={text} onChange={(e) => setText(e.target.value)} data-testid="plan-ann-text" />
          <select className="h-8 rounded-lg border border-border bg-background px-2 text-xs" value={vis} onChange={(e) => setVis(e.target.value)} data-testid="plan-ann-visibility"><option value="internal">Interne</option><option value="shared">Partagée</option></select></>}
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={showInternal} onChange={(e) => setShowInternal(e.target.checked)} data-testid="plan-show-internal" />Afficher les annotations internes</label>
        {plan.page_count > 1 && <span className="flex items-center gap-1 text-xs"><Button size="sm" variant="outline" disabled={!page} onClick={() => setPage(page - 1)}>‹</Button>page {page + 1} / {plan.page_count}<Button size="sm" variant="outline" disabled={page >= plan.page_count - 1} onClick={() => setPage(page + 1)}>›</Button></span>}
        <span className="flex-1" />{write && <Button size="sm" onClick={save} data-testid="plan-ann-save">Enregistrer</Button>}</div>
      <div ref={box} className="relative w-full cursor-crosshair select-none" onClick={click} data-testid="plan-canvas">
        {url && <img src={url} alt={plan.filename} className="block w-full" draggable={false} />}
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
          {shown.filter((a) => a.type === "arrow").map((a) => <line key={a.id} x1={a.geometry.x1} y1={a.geometry.y1} x2={a.geometry.x2} y2={a.geometry.y2} stroke={col(a)} strokeWidth="3" vectorEffect="non-scaling-stroke" />)}
          {shown.filter((a) => a.type === "rect").map((a) => <rect key={a.id} x={Math.min(a.geometry.x1, a.geometry.x2)} y={Math.min(a.geometry.y1, a.geometry.y2)} width={Math.abs(a.geometry.x2 - a.geometry.x1)} height={Math.abs(a.geometry.y2 - a.geometry.y1)} fill="none" stroke={col(a)} strokeWidth="3" vectorEffect="non-scaling-stroke" />)}
        </svg>
        {shown.filter((a) => a.type === "arrow").map((a) => <span key={a.id} className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${a.geometry.x2 * 100}%`, top: `${a.geometry.y2 * 100}%`, background: col(a) }} />)}
        {shown.filter((a) => a.type === "pin" || a.type === "text").map((a) => <span key={a.id} className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full px-2 py-0.5 text-xs font-bold text-white" style={{ left: `${a.geometry.x * 100}%`, top: `${a.geometry.y * 100}%`, background: col(a) }}>{a.type === "pin" ? pins.indexOf(a) + 1 : a.text}</span>)}
        {first && <span className="absolute h-2 w-2 rounded-full bg-black" style={{ left: `${first.x * 100}%`, top: `${first.y * 100}%` }} />}
      </div>
      <div className="divide-y divide-border text-sm" data-testid="plan-ann-list">{anns.filter((a) => showInternal || a.visibility === "shared").map((a) => (
        <div key={a.id} className={`flex flex-wrap items-center gap-2 py-1 ${a.status === "resolved" ? "opacity-50" : ""}`}><b style={{ color: col(a) }}>{a.type === "pin" ? `Pastille ${pins.indexOf(a) + 1}` : { arrow: "Flèche", rect: "Rectangle", text: "Texte" }[a.type]}</b><span className="flex-1">{a.text}</span><span className="text-xs text-muted-foreground">p. {a.page + 1} · {a.visibility === "shared" ? "partagée" : "interne"}{a.author ? ` · ${a.author}` : ""}</span>
          {write && <><button type="button" className="text-xs underline" onClick={() => setAnns(anns.map((x) => (x.id === a.id ? { ...x, status: x.status === "open" ? "resolved" : "open" } : x)))}>{a.status === "open" ? "résoudre" : "rouvrir"}</button><button type="button" aria-label="Supprimer" onClick={() => setAnns(anns.filter((x) => x.id !== a.id))}><Trash2 className="h-3.5 w-3.5" /></button></>}</div>))}</div>
    </DialogContent></Dialog>);
}

export function TabDeroule({ ev, write }) {
  const [d, setD] = useState(null);
  const [plans, setPlans] = useState([]);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [ins, setIns] = useState(null);
  const [plan, setPlan] = useState(null);
  const [zone, setZone] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const load = useCallback(() => { api.get(`/events/${ev.id}/schedule`).then((r) => setD(r.data)).catch(ko); api.get(`/events/${ev.id}/organizer-plans`).then((r) => setPlans(r.data)).catch(ko); }, [ev.id]);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const importSrc = (file) => { const fd = new FormData(); if (file) fd.append("file", file); fd.append("text", file ? "" : text); setBusy(true); api.post(`/events/${ev.id}/schedule/sources`, fd).then((r) => { setReview(r.data); setText(""); }).catch(ko).finally(() => setBusy(false)); };
  const validate = (rows) => api.post(`/events/${ev.id}/schedule/validate`, { source_id: review.id, steps: rows.map((r) => ({ title: r.title, start: r.start.slice(0, 16), duration_min: r.duration_min, description: r.description || "", space_label: r.space_label || "", people: r.people || "", relevance: r.relevance })) }).then((r) => { setD(r.data); setReview(null); toast.success("Déroulé généré"); }).catch(ko);
  const patch = (id, body) => api.put(`/schedule/steps/${id}`, body).then((r) => setD(r.data)).catch(ko);
  const insert = () => api.post(`/events/${ev.id}/schedule/steps`, { after_id: ins.after, title: ins.title, duration_min: Number(ins.dur) || 0 }).then((r) => { setD(r.data); setIns(null); }).catch(ko);
  const addPlan = (file) => { const fd = new FormData(); fd.append("file", file); fd.append("zone_label", zone); api.post(`/events/${ev.id}/organizer-plans`, fd).then(() => { toast.success("Plan ajouté"); setZone(""); load(); }).catch(ko); };
  const drop = (fn) => ({ onDragOver: (e) => e.preventDefault(), onDrop: (e) => { e.preventDefault(); if (write && e.dataTransfer.files[0]) fn(e.dataTransfer.files[0]); } });
  const days = [...new Set(d.steps.map((s) => s.start.slice(0, 10)))];
  const plus = (after) => write && (ins?.after === after ? (
    <div className="flex flex-wrap items-center gap-2 py-1 pl-4" data-testid="step-insert-form"><Input className="h-8 w-64" autoFocus placeholder="Intitulé de l'étape" value={ins.title} onChange={(e) => setIns({ ...ins, title: e.target.value })} data-testid="step-insert-title" /><Input className="h-8 w-20" type="number" min="0" value={ins.dur} onChange={(e) => setIns({ ...ins, dur: e.target.value })} data-testid="step-insert-duration" /><span className="text-xs">min</span><Button size="sm" disabled={!ins.title.trim()} onClick={insert} data-testid="step-insert-save">Insérer</Button><Button size="sm" variant="ghost" onClick={() => setIns(null)}>Annuler</Button></div>
  ) : <button type="button" className="ml-4 flex items-center text-xs text-muted-foreground opacity-40 hover:opacity-100" onClick={() => setIns({ after, title: "", dur: 15 })} data-testid={`step-insert-${after}`}><Plus className="h-3 w-3" />insérer une étape ici</button>);
  return (
    <div className="space-y-6" data-testid="deroule-tab">
      {write && <div className="rounded-2xl border border-dashed border-border p-4" {...drop(importSrc)} data-testid="schedule-drop">
        <div className="mb-2 font-semibold">Planning de l'organisateur {d.sources.length > 0 && <span className="text-xs font-normal text-muted-foreground">— {d.sources.map((s) => `V${s.version} ${s.filename} (${fmtDate(s.received_at)})`).join(" · ")}</span>}</div>
        <div className="flex flex-wrap items-center gap-2 text-sm"><label className="cursor-pointer rounded-full border border-border px-3 py-1.5 text-xs font-semibold hover:bg-secondary">{d.sources.length ? "Déposer une nouvelle version" : "Ajouter le planning de l'organisateur"} (PDF ou image)<input type="file" className="hidden" accept="application/pdf,image/*" onChange={(e) => e.target.files[0] && importSrc(e.target.files[0])} data-testid="schedule-file" /></label>ou glissez le fichier ici
          {busy && <span className="text-xs text-muted-foreground" data-testid="schedule-busy">Lecture du planning en cours…</span>}</div>
        <textarea className="mt-2 h-20 w-full rounded-lg border border-border bg-background p-2 text-sm" placeholder="… ou collez ici le texte du planning (mail, WhatsApp)" value={text} onChange={(e) => setText(e.target.value)} data-testid="schedule-text" />
        <Button size="sm" variant="outline" disabled={busy || text.trim().length < 10} onClick={() => importSrc(null)} data-testid="schedule-text-import">Lire ce texte</Button></div>}
      <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="roadmap-actions"><b>Feuille de route PDF :</b>{[["team", "Équipe"], ["dj", "DJ"], ["organizer", "Organisateur"]].map(([k, l]) => <Button key={k} size="sm" variant="outline" disabled={!d.steps.length} onClick={() => downloadPdf(`/events/${ev.id}/schedule/roadmap?audience=${k}`, `feuille-de-route-${k}-${ev.code}.pdf`).catch(ko)} data-testid={`roadmap-${k}`}>{l}</Button>)}{write && d.steps.length > 0 && <RoadmapSend eid={ev.id} />}<span className="text-xs text-muted-foreground">La version Organisateur ne contient ni notes internes ni bascules de matériel.</span></div>
      {d.conflicts > 0 && <p className="rounded-xl bg-red-500/10 p-3 text-sm font-semibold text-red-700" data-testid="schedule-conflicts">{d.conflicts} conflit(s) d'horaire à régler.</p>}
      {!d.steps.length && <p className="text-sm text-muted-foreground">Aucune étape pour l'instant.{write && <button type="button" className="ml-2 underline" onClick={() => setIns({ after: "", title: "", dur: 15 })} data-testid="step-insert-first">Ajouter une première étape</button>}</p>}
      {!d.steps.length && ins && plus("")}
      {days.map((day) => (
        <div key={day} data-testid={`schedule-day-${day}`}><h3 className="mb-2 font-display text-lg">{fmtDate(day)}</h3>
          {d.steps.filter((s) => s.start.slice(0, 10) === day).map((s) => (
            <div key={s.id}>
              <div className={`flex flex-wrap items-center gap-2 rounded-lg border border-l-4 border-border ${PHASE[s.phase] || ""} px-3 py-2 text-sm ${s.status === "done" ? "opacity-50" : ""}`} data-testid={`step-${s.id}`}>
                {write && <input type="checkbox" aria-label="Fait" checked={s.status === "done"} onChange={(e) => patch(s.id, { status: e.target.checked ? "done" : "planned" })} />}
                <b className="w-24 whitespace-nowrap" data-testid={`step-time-${s.id}`}>{hm(s.start)}{s.duration_min ? ` – ${hm(s.end)}` : ""}</b>
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${SRC[s.source][1]}`}>{SRC[s.source][0]}</span>
                <span className="min-w-0 flex-1" data-testid={`step-title-${s.id}`}>{s.title}{s.space_label && <span className="ml-2 text-xs text-muted-foreground">{s.space_label}</span>}{s.relevance === "to_check" && <span className="ml-2 text-xs font-semibold text-amber-600">à vérifier</span>}</span>
                {write && <><Input className="h-7 w-16 px-1" type="number" min="0" defaultValue={s.duration_min} key={s.duration_min} onBlur={(e) => Number(e.target.value) !== s.duration_min && patch(s.id, { duration_min: Number(e.target.value) || 0 })} aria-label="Durée (min)" data-testid={`step-duration-${s.id}`} />
                  <button type="button" title={s.time_mode === "fixed" ? "Heure fixe (cliquer pour enchaîner à l'étape précédente)" : "Enchaînée (cliquer pour fixer l'heure)"} onClick={() => patch(s.id, { time_mode: s.time_mode === "fixed" ? "chained" : "fixed" })} data-testid={`step-mode-${s.id}`}>{s.time_mode === "fixed" ? <Lock className="h-4 w-4" /> : <Unlock className="h-4 w-4 text-muted-foreground" />}</button>
                  <button type="button" aria-label="Monter" onClick={() => patch(s.id, { move: -1 })}><ArrowUp className="h-4 w-4" /></button><button type="button" aria-label="Descendre" onClick={() => patch(s.id, { move: 1 })}><ArrowDown className="h-4 w-4" /></button>
                  <button type="button" className="text-xs underline" onClick={() => patch(s.id, s.source === "organizer" ? { visible: false } : { deleted: true })} data-testid={`step-hide-${s.id}`}>{s.source === "organizer" ? "masquer" : "supprimer"}</button></>}
                {s.conflict && <span className="w-full text-xs font-semibold text-red-600" data-testid={`step-conflict-${s.id}`}>{s.conflict}</span>}
              </div>
              {plus(s.id)}
            </div>))}
        </div>))}
      {d.hidden.length > 0 && <div data-testid="schedule-hidden"><button type="button" className="text-sm underline" onClick={() => setShowHidden(!showHidden)} data-testid="schedule-hidden-toggle">Masquées ({d.hidden.length})</button>
        {showHidden && d.hidden.map((s) => <div key={s.id} className="flex items-center gap-2 py-1 text-sm text-muted-foreground"><span className="w-28">{fmtDate(s.start.slice(0, 10))} {hm(s.start)}</span><span className="flex-1">{s.title}</span>{write && <button type="button" className="underline" onClick={() => patch(s.id, { visible: true })} data-testid={`step-restore-${s.id}`}>réintégrer</button>}</div>)}</div>}
      <div className="rounded-2xl border border-border p-4" {...drop(addPlan)} data-testid="organizer-plans">
        <div className="mb-2 font-semibold">Plans organisateur</div>
        {write && <div className="mb-3 flex flex-wrap items-center gap-2 text-sm"><Input className="h-9 w-56" placeholder="Zone (Cérémonie, Dîner…)" value={zone} onChange={(e) => setZone(e.target.value)} data-testid="plan-zone" /><label className="cursor-pointer rounded-full border border-border px-3 py-1.5 text-xs font-semibold hover:bg-secondary">Ajouter un plan (PDF ou image)<input type="file" className="hidden" accept="application/pdf,image/*" onChange={(e) => e.target.files[0] && addPlan(e.target.files[0])} data-testid="plan-file" /></label><span className="text-xs text-muted-foreground">Même zone = nouvelle version du plan.</span></div>}
        {!plans.length && <p className="text-sm text-muted-foreground">Aucun plan déposé.</p>}
        <div className="divide-y divide-border">{plans.map((p) => <button key={p.id} type="button" className="flex w-full flex-wrap items-center gap-2 py-2 text-left text-sm hover:bg-secondary/50" onClick={() => setPlan(p)} data-testid={`plan-${p.id}`}><b>{p.filename}</b><span className="rounded-full bg-secondary px-2 py-0.5 text-xs">V{p.version}</span>{p.zone_label && <span className="text-xs">{p.zone_label}</span>}<span className="flex-1" /><span className="text-xs text-muted-foreground">{p.page_count} page(s) · {p.annotations.length} annotation(s) · {p.uploaded_by} · {fmtDate(p.uploaded_at)}</span></button>)}</div>
      </div>
      {review && <Review src={review} onClose={() => setReview(null)} onValidate={validate} />}
      {plan && <PlanViewer plan={plan} write={write} onClose={() => setPlan(null)} onSaved={load} />}
    </div>);
}
