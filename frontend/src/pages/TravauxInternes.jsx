import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2, Repeat, Layers, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { PageHeader, Loading, Field } from "@/components/common";
import { TrashBtn } from "@/components/Trash";
import { api, errMsg } from "@/lib/api";
import { FileList } from "@/lib/files";
import { fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

// Travaux internes (lot 1) : ordres de travail, backlog, chantiers en étapes, modèles et récurrences.
const ko = (e) => toast.error(errMsg(e));
const sel = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm";
const PRIO = { basse: ["Basse", "bg-secondary text-muted-foreground"], normale: ["Normale", "bg-secondary"], haute: ["Haute", "bg-amber-500/15 text-amber-700 dark:text-amber-300"], urgente: ["Urgente", "bg-red-500/15 text-red-700 dark:text-red-300"] };
const STATUS = { a_planifier: "À planifier", planifie: "Planifié", en_cours: "En cours", en_pause: "En pause", fait: "Fait", reporte: "Reporté", annule: "Annulé" };
const EFFECTS = { unavailable: "Indisponible pendant la tâche", consume: "Consommé", produce: "Produit (construction)" };
const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const EMPTY = { title: "", type: "autre", description: "", priority: "normale", warehouse_id: "", zone: "", site: "", vehicle_id: "", event_id: "", scheduled_start: "", scheduled_end: "", deadline: "",
  estimated_minutes: 60, required_people: 1, required_skills: [], assignee_ids: [], lead_id: "", items: [], tools: [], checklist: [], attachments: [], photos_before: [], photos_after: [], status: null,
  parent_id: "", depends_on_ids: [], min_delay_after_hours: 0, step_order: 0, template_id: "" };
const hm = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60}` : ""}` : `${m} min`);
const slot = (w) => (w.scheduled_start ? `${fmtDate(w.scheduled_start.slice(0, 10), { weekday: "short", day: "numeric", month: "short" })} ${w.scheduled_start.slice(11, 16)}–${(w.scheduled_end || "").slice(11, 16)}` : "");

function People({ people, value, onChange, testid }) {
  return (
    <div className="flex flex-wrap gap-1.5" data-testid={testid}>{people.map((p) => { const on = value.includes(p.id); return (
      <button type="button" key={p.id} aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== p.id) : [...value, p.id])}
        className={`rounded-full border px-3 py-1 text-xs ${on ? "border-primary bg-primary text-primary-foreground" : "border-border"}`}>{p.name}</button>); })}</div>
  );
}

function Lines({ label, rows, onChange, products, effects, testid }) {
  const set = (i, k, v) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <div className="col-span-2" data-testid={testid}>
      <div className="mb-1.5 flex items-center justify-between text-xs font-medium text-muted-foreground">{label}
        <button type="button" className="text-primary" onClick={() => onChange([...rows, { product_id: "", label: "", quantity: 1, ...(effects ? { effect: "unavailable" } : {}) }])}>+ Ajouter</button></div>
      {rows.map((r, i) => (
        <div key={i} className="mb-1.5 grid grid-cols-12 gap-2">
          <select className={`${sel} col-span-5`} value={r.product_id} onChange={(e) => set(i, "product_id", e.target.value)}>
            <option value="">{effects && r.effect === "produce" ? "Nouvel article (libellé →)" : "Choisir un article"}</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          <Input className="col-span-3" placeholder="Libellé" value={r.label} onChange={(e) => set(i, "label", e.target.value)} />
          <Input className="col-span-1" type="number" min="0.01" step="any" value={r.quantity} onChange={(e) => set(i, "quantity", Number(e.target.value))} />
          {effects ? <select className={`${sel} col-span-2`} value={r.effect} onChange={(e) => set(i, "effect", e.target.value)}>{Object.entries(EFFECTS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select> : <span className="col-span-2" />}
          <button type="button" className="col-span-1 text-muted-foreground" aria-label="Retirer" onClick={() => onChange(rows.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
        </div>))}
    </div>
  );
}

function WorkDialog({ work, ctx, onClose, onSaved }) {
  const [f, setF] = useState(EMPTY);
  const [item, setItem] = useState("");
  const [full, setFull] = useState(null);
  useEffect(() => {
    if (!work) return;
    setF({ ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).map((k) => [k, work[k] ?? EMPTY[k]])) });
    setFull(null);
    if (work.id && !work.parent_id) api.get(`/work-orders/${work.id}`).then((r) => setFull(r.data)).catch(() => {});
  }, [work]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const isStep = !!f.parent_id;
  const siblings = (full?.steps || []).filter((s) => s.id !== work?.id);
  const submit = (e) => {
    e.preventDefault();
    const body = { ...f, estimated_minutes: Number(f.estimated_minutes) || 0, required_people: Number(f.required_people) || 1, min_delay_after_hours: Number(f.min_delay_after_hours) || 0 };
    if (!work.id) delete body.status;
    (work.id ? api.patch(`/work-orders/${work.id}`, body) : api.post("/work-orders", body)).then(() => { toast.success("Travail enregistré"); onSaved(); onClose(); }).catch(ko);
  };
  return (
    <Dialog open={!!work} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{work?.id ? (isStep ? "Étape du chantier" : "Travail interne") : (isStep ? "Nouvelle étape" : "Nouveau travail interne")}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-4" data-testid="work-form">
          {!work?.id && !isStep && ctx.templates.length > 0 && (
            <Field label="Partir d'un modèle" className="col-span-2"><select className={sel} value={f.template_id} onChange={(e) => { const t = ctx.templates.find((x) => x.id === e.target.value); setF(t ? { ...f, template_id: t.id, title: t.title, type: t.type, description: t.description, estimated_minutes: t.estimated_minutes, required_people: t.required_people, required_skills: t.required_skills, checklist: t.checklist, items: t.items, tools: t.tools, priority: t.priority, warehouse_id: t.warehouse_id, zone: t.zone } : { ...f, template_id: "" }); }} data-testid="work-template">
              <option value="">Aucun</option>{ctx.templates.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</select></Field>)}
          <Field label="Titre" className="col-span-2"><Input required value={f.title} onChange={set("title")} data-testid="work-title" /></Field>
          <Field label="Type"><select className={sel} value={f.type} onChange={set("type")} data-testid="work-type">{ctx.types.filter((t) => t.active || t.key === f.type).map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</select></Field>
          <Field label="Priorité"><select className={sel} value={f.priority} onChange={set("priority")} data-testid="work-priority">{Object.entries(PRIO).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Description" className="col-span-2"><Textarea rows={2} value={f.description} onChange={set("description")} /></Field>
          <Field label="Entrepôt"><select className={sel} value={f.warehouse_id} onChange={set("warehouse_id")}><option value="">—</option>{ctx.warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
          <Field label="Zone (rayonnage, atelier, quai)"><Input value={f.zone} onChange={set("zone")} /></Field>
          <Field label="Site extérieur"><Input value={f.site} onChange={set("site")} /></Field>
          <Field label="Véhicule"><select className={sel} value={f.vehicle_id} onChange={set("vehicle_id")}><option value="">—</option>{ctx.vehicles.map((v) => <option key={v.id} value={v.id}>{v.name || v.plate}</option>)}</select></Field>
          <Field label="Événement lié (coût imputé à sa rentabilité)" className="col-span-2"><select className={sel} value={f.event_id} onChange={set("event_id")} data-testid="work-event"><option value="">Aucun — frais de structure</option>{ctx.events.map((e) => <option key={e.id} value={e.id}>{e.code} — {e.title}</option>)}</select></Field>
          <Field label="Début (vide = à planifier)"><Input type="datetime-local" value={f.scheduled_start} onChange={(e) => setF({ ...f, scheduled_start: e.target.value, scheduled_end: e.target.value ? f.scheduled_end : "" })} data-testid="work-start" /></Field>
          <Field label="Fin (vide = calculée)"><Input type="datetime-local" value={f.scheduled_end} disabled={!f.scheduled_start} onChange={set("scheduled_end")} /></Field>
          <Field label="Date limite souhaitée"><Input type="date" value={f.deadline} onChange={set("deadline")} data-testid="work-deadline" /></Field>
          <Field label="Statut">{work?.id ? <select className={sel} value={f.status || ""} onChange={set("status")} data-testid="work-status">{Object.entries(STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select> : <div className="pt-2 text-sm text-muted-foreground">{f.scheduled_start ? "Planifié" : "À planifier"}</div>}</Field>
          <Field label="Durée estimée (minutes-personne)"><Input type="number" min="0" value={f.estimated_minutes} onChange={set("estimated_minutes")} data-testid="work-minutes" /></Field>
          <Field label="Effectif requis"><Input type="number" min="1" value={f.required_people} onChange={set("required_people")} data-testid="work-people" /></Field>
          <Field label="Compétences requises (séparées par des virgules)" className="col-span-2"><Input value={f.required_skills.join(", ")} onChange={(e) => setF({ ...f, required_skills: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} placeholder="menuiserie, cariste…" /></Field>
          <div className="col-span-2"><div className="mb-1.5 text-xs font-medium text-muted-foreground">Personnes affectées</div><People people={ctx.team} value={f.assignee_ids} onChange={(v) => setF({ ...f, assignee_ids: v, lead_id: v.includes(f.lead_id) ? f.lead_id : "" })} testid="work-assignees" /></div>
          <Field label="Chef d'équipe"><select className={sel} value={f.lead_id} onChange={set("lead_id")}><option value="">—</option>{ctx.team.filter((p) => f.assignee_ids.includes(p.id)).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          {isStep && <>
            <Field label="Après l'étape"><select className={sel} value={f.depends_on_ids[0] || ""} onChange={(e) => setF({ ...f, depends_on_ids: e.target.value ? [e.target.value] : [] })} data-testid="work-depends">
              <option value="">—</option>{(ctx.siblings || siblings).filter((s) => s.id !== work?.id).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></Field>
            <Field label="Délai minimum après (h, ex. séchage)"><Input type="number" min="0" value={f.min_delay_after_hours} onChange={set("min_delay_after_hours")} data-testid="work-delay" /></Field>
            <Field label="Ordre"><Input type="number" value={f.step_order} onChange={set("step_order")} /></Field>
          </>}
          <Lines label="Matériel concerné" rows={f.items} onChange={(v) => setF({ ...f, items: v })} products={ctx.products} effects testid="work-items" />
          <Lines label="Outillage nécessaire" rows={f.tools} onChange={(v) => setF({ ...f, tools: v })} products={ctx.products} testid="work-tools" />
          <div className="col-span-2"><div className="mb-1.5 text-xs font-medium text-muted-foreground">Check-list</div>
            {f.checklist.map((c, i) => <label key={i} className="mb-1 flex items-center gap-2 text-sm"><input type="checkbox" checked={c.done} onChange={(e) => setF({ ...f, checklist: f.checklist.map((x, j) => (j === i ? { ...x, done: e.target.checked } : x)) })} />{c.label}
              <button type="button" className="ml-auto text-muted-foreground" onClick={() => setF({ ...f, checklist: f.checklist.filter((_, j) => j !== i) })} aria-label="Retirer"><Trash2 className="h-3.5 w-3.5" /></button></label>)}
            <div className="flex gap-2"><Input value={item} onChange={(e) => setItem(e.target.value)} placeholder="Ajouter un point" onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (item.trim()) { setF({ ...f, checklist: [...f.checklist, { label: item.trim(), done: false }] }); setItem(""); } } }} data-testid="work-check-input" /></div></div>
          <div className="col-span-2 grid gap-3 md:grid-cols-3">
            <FileList label="Plans, croquis" value={f.attachments} onChange={(v) => setF({ ...f, attachments: v })} testid="work-attachments" />
            <FileList label="Photos avant" value={f.photos_before} onChange={(v) => setF({ ...f, photos_before: v })} testid="work-photos-before" />
            <FileList label="Photos après" value={f.photos_after} onChange={(v) => setF({ ...f, photos_after: v })} testid="work-photos-after" />
          </div>
          {full && !isStep && (
            <div className="col-span-2 rounded-xl border border-border p-3" data-testid="work-steps">
              <div className="mb-2 flex items-center justify-between"><div className="text-sm font-semibold">Étapes du chantier <span className="font-normal text-muted-foreground">— {full.progress.done}/{full.progress.total} faites ({full.progress.percent} %), {hm(full.progress.actual_minutes)} réalisées / {hm(full.progress.estimated_minutes)} estimées</span></div>
                <Button type="button" size="sm" variant="outline" onClick={() => onSaved({ openStep: { ...EMPTY, parent_id: work.id, type: f.type, event_id: f.event_id, warehouse_id: f.warehouse_id, step_order: full.steps.length + 1 }, siblings: full.steps })} data-testid="work-add-step"><Plus />Étape</Button></div>
              <div className="h-1.5 overflow-hidden rounded-full bg-secondary"><div className="h-full bg-primary" style={{ width: `${full.progress.percent}%` }} /></div>
              {full.steps.map((s) => <button type="button" key={s.id} onClick={() => onSaved({ openStep: s, siblings: full.steps })} className="mt-2 flex w-full items-center justify-between rounded-lg bg-secondary/60 px-3 py-2 text-left text-sm">
                <span>{s.step_order}. {s.title}{s.depends_on_ids?.length ? <span className="text-muted-foreground"> — après {full.steps.find((x) => x.id === s.depends_on_ids[0])?.title}{s.min_delay_after_hours ? ` + ${s.min_delay_after_hours} h` : ""}</span> : null}</span>
                <span className="text-xs text-muted-foreground">{slot(s) || "à planifier"} · {STATUS[s.status]}</span></button>)}
            </div>)}
          <DialogFooter className="col-span-2">
            {work?.id && <TrashBtn kind="work_order" id={work.id} name={f.title} onDone={() => { onSaved(); onClose(); }} />}
            <Button type="submit" data-testid="work-save">Enregistrer</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Row({ w, ctx, onOpen }) {
  const names = (w.assignee_ids || []).map((id) => ctx.team.find((p) => p.id === id)?.name).filter(Boolean);
  const type = ctx.types.find((t) => t.key === w.type)?.label || w.type;
  return (
    <button onClick={() => onOpen(w)} className="flex w-full items-start gap-3 rounded-xl border border-border bg-card p-3 text-left" data-testid={`work-${w.id}`}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-medium">{w.title}{w.recurrence_id && <Repeat className="h-3.5 w-3.5 text-muted-foreground" aria-label="Récurrent" />}</div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span>{type}</span>
          <span className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${PRIO[w.priority]?.[1]}`}>{PRIO[w.priority]?.[0]}</span>
          {w.scheduled_start ? <span>{slot(w)}</span> : <span>{hm(w.estimated_minutes)} · {w.required_people} pers.</span>}
          {w.deadline && <span className={w.late ? "flex items-center gap-1 font-semibold text-red-600" : ""} data-testid={w.late ? `work-late-${w.id}` : undefined}>{w.late && <AlertTriangle className="h-3 w-3" />}avant le {fmtDate(w.deadline, { day: "numeric", month: "short" })}</span>}
          {names.length > 0 && <span>{names.join(", ")}</span>}
          {w.event_title && <Link to={`/evenements/${w.event_id}`} onClick={(e) => e.stopPropagation()} className="text-primary hover:underline">{w.event_title}</Link>}
        </div>
      </div>
      <span className="shrink-0 rounded-full bg-secondary px-2.5 py-1 text-[11px] font-semibold">{STATUS[w.status]}</span>
    </button>
  );
}

function Templates({ ctx, reload }) {
  const [t, setT] = useState(null);
  const save = (e) => { e.preventDefault(); const b = { ...t, estimated_minutes: Number(t.estimated_minutes) || 0, required_people: Number(t.required_people) || 1 };
    (t.id ? api.put(`/work-templates/${t.id}`, b) : api.post("/work-templates", b)).then(() => { toast.success("Modèle enregistré"); setT(null); reload(); }).catch(ko); };
  const blank = { title: "", type: "autre", description: "", estimated_minutes: 60, required_people: 1, required_skills: [], checklist: [], items: [], tools: [], priority: "normale", warehouse_id: "", zone: "" };
  return (
    <div data-testid="work-templates">
      <Button variant="outline" onClick={() => setT(blank)} className="mb-3" data-testid="new-template"><Plus />Modèle</Button>
      <div className="space-y-2">{ctx.templates.map((x) => <button key={x.id} onClick={() => setT(x)} className="flex w-full justify-between rounded-xl border border-border bg-card p-3 text-left text-sm">
        <span className="font-medium">{x.title}</span><span className="text-xs text-muted-foreground">{ctx.types.find((k) => k.key === x.type)?.label} · {hm(x.estimated_minutes)} · {x.required_people} pers. · {x.checklist.length} point(s)</span></button>)}
        {!ctx.templates.length && <p className="text-sm text-muted-foreground">Aucun modèle. Un modèle sert à créer vite un travail fréquent et à le rendre récurrent.</p>}</div>
      <Dialog open={!!t} onOpenChange={(o) => !o && setT(null)}>
        <DialogContent className="max-w-xl"><DialogHeader><DialogTitle>{t?.id ? "Modifier le modèle" : "Nouveau modèle"}</DialogTitle></DialogHeader>
          {t && <form onSubmit={save} className="grid grid-cols-2 gap-4" data-testid="template-form">
            <Field label="Titre" className="col-span-2"><Input required value={t.title} onChange={(e) => setT({ ...t, title: e.target.value })} data-testid="template-title" /></Field>
            <Field label="Type"><select className={sel} value={t.type} onChange={(e) => setT({ ...t, type: e.target.value })}>{ctx.types.filter((k) => k.active).map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}</select></Field>
            <Field label="Priorité"><select className={sel} value={t.priority} onChange={(e) => setT({ ...t, priority: e.target.value })}>{Object.entries(PRIO).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <Field label="Durée (minutes-personne)"><Input type="number" value={t.estimated_minutes} onChange={(e) => setT({ ...t, estimated_minutes: e.target.value })} /></Field>
            <Field label="Effectif"><Input type="number" min="1" value={t.required_people} onChange={(e) => setT({ ...t, required_people: e.target.value })} /></Field>
            <Field label="Check-list (un point par ligne)" className="col-span-2"><Textarea rows={4} value={t.checklist.map((c) => c.label).join("\n")} onChange={(e) => setT({ ...t, checklist: e.target.value.split("\n").filter((l) => l.trim()).map((label) => ({ label, done: false })) })} /></Field>
            <DialogFooter className="col-span-2">{t.id && <Button type="button" variant="ghost" onClick={() => api.delete(`/work-templates/${t.id}`).then(() => { setT(null); reload(); }).catch(ko)}>Supprimer</Button>}<Button type="submit" data-testid="template-save">Enregistrer</Button></DialogFooter>
          </form>}</DialogContent></Dialog>
    </div>
  );
}

function Recurrences({ ctx, reload }) {
  const [r, setR] = useState(null);
  const today = new Date().toISOString().slice(0, 10);
  const save = (e) => { e.preventDefault(); const b = { ...r, interval: Number(r.interval) || 1, monthday: Number(r.monthday) || 1 };
    (r.id ? api.put(`/work-recurrences/${r.id}`, b) : api.post("/work-recurrences", b)).then((x) => { toast.success(`${x.data.generated} occurrence(s) planifiée(s) sur 8 semaines`); setR(null); reload(); }).catch(ko); };
  const label = (x) => (x.freq === "weekly" ? `${x.interval > 1 ? `toutes les ${x.interval} semaines` : "chaque semaine"}, ${x.weekdays.map((d) => DAYS[d]).join(", ")}` : `le ${x.monthday} ${x.interval > 1 ? `tous les ${x.interval} mois` : "de chaque mois"}`) + ` à ${x.start_time}`;
  return (
    <div data-testid="work-recurrences">
      <Button variant="outline" disabled={!ctx.templates.length} onClick={() => setR({ template_id: ctx.templates[0]?.id, freq: "weekly", interval: 1, weekdays: [0], monthday: 1, start_time: "08:00", end_time: "", start: today, end: "", default_assignee_ids: [], active: true })} className="mb-3" data-testid="new-recurrence"><Plus />Tâche récurrente</Button>
      {!ctx.templates.length && <p className="mb-3 text-sm text-muted-foreground">Créez d'abord un modèle.</p>}
      <div className="space-y-2">{ctx.recurrences.map((x) => <button key={x.id} onClick={() => setR(x)} className="flex w-full justify-between rounded-xl border border-border bg-card p-3 text-left text-sm">
        <span className="font-medium">{ctx.templates.find((t) => t.id === x.template_id)?.title || "Modèle supprimé"}</span><span className="text-xs text-muted-foreground">{label(x)}{x.active ? "" : " · inactive"}</span></button>)}</div>
      <Dialog open={!!r} onOpenChange={(o) => !o && setR(null)}>
        <DialogContent className="max-w-xl"><DialogHeader><DialogTitle>Tâche récurrente</DialogTitle></DialogHeader>
          {r && <form onSubmit={save} className="grid grid-cols-2 gap-4" data-testid="recurrence-form">
            <Field label="Modèle" className="col-span-2"><select className={sel} value={r.template_id} onChange={(e) => setR({ ...r, template_id: e.target.value })}>{ctx.templates.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</select></Field>
            <Field label="Fréquence"><select className={sel} value={r.freq} onChange={(e) => setR({ ...r, freq: e.target.value })} data-testid="recurrence-freq"><option value="weekly">Hebdomadaire</option><option value="monthly">Mensuelle</option></select></Field>
            <Field label={r.freq === "weekly" ? "Toutes les N semaines" : "Tous les N mois (6 = semestriel)"}><Input type="number" min="1" value={r.interval} onChange={(e) => setR({ ...r, interval: e.target.value })} /></Field>
            {r.freq === "weekly" ? <div className="col-span-2 flex flex-wrap gap-1.5">{DAYS.map((d, i) => { const on = r.weekdays.includes(i); return <button type="button" key={d} aria-pressed={on} onClick={() => setR({ ...r, weekdays: on ? r.weekdays.filter((x) => x !== i) : [...r.weekdays, i].sort() })} className={`rounded-full border px-3 py-1 text-xs ${on ? "border-primary bg-primary text-primary-foreground" : "border-border"}`}>{d}</button>; })}</div>
              : <Field label="Jour du mois (1 à 28)"><Input type="number" min="1" max="28" value={r.monthday} onChange={(e) => setR({ ...r, monthday: e.target.value })} /></Field>}
            <Field label="Heure de début"><Input type="time" value={r.start_time} onChange={(e) => setR({ ...r, start_time: e.target.value })} /></Field>
            <Field label="Heure de fin (facultatif)"><Input type="time" value={r.end_time} onChange={(e) => setR({ ...r, end_time: e.target.value })} /></Field>
            <Field label="À partir du"><Input type="date" required value={r.start} onChange={(e) => setR({ ...r, start: e.target.value })} /></Field>
            <Field label="Jusqu'au (facultatif)"><Input type="date" value={r.end} onChange={(e) => setR({ ...r, end: e.target.value })} /></Field>
            <div className="col-span-2"><div className="mb-1.5 text-xs font-medium text-muted-foreground">Personnes par défaut</div><People people={ctx.team} value={r.default_assignee_ids} onChange={(v) => setR({ ...r, default_assignee_ids: v })} /></div>
            <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={r.active} onChange={(e) => setR({ ...r, active: e.target.checked })} />Active</label>
            <DialogFooter className="col-span-2">{r.id && <Button type="button" variant="ghost" onClick={() => api.delete(`/work-recurrences/${r.id}`).then(() => { setR(null); reload(); }).catch(ko)}>Supprimer</Button>}<Button type="submit" data-testid="recurrence-save">Enregistrer</Button></DialogFooter>
          </form>}</DialogContent></Dialog>
    </div>
  );
}

export default function TravauxInternes() {
  const { can } = useMe();
  const write = can("catalog:write");
  const [tab, setTab] = useState("backlog");
  const [d, setD] = useState(null);
  const [ref, setRef] = useState({ team: [], events: [], warehouses: [], vehicles: [], products: [], templates: [], recurrences: [] });
  const [edit, setEdit] = useState(null);
  const [siblings, setSiblings] = useState(null);
  const [type, setType] = useState("");
  const load = useCallback(() => api.get("/work-orders", { params: tab === "backlog" ? { backlog: true } : { status: tab === "planned" ? "planifie,en_cours,en_pause" : tab === "done" ? "fait,annule" : "" } }).then((r) => setD(r.data)).catch(ko), [tab]);
  const loadRef = useCallback(() => Promise.all([
    api.get("/team").catch(() => ({ data: [] })), api.get("/events").catch(() => ({ data: [] })), api.get("/warehouses").catch(() => ({ data: [] })),
    api.get("/vehicles").catch(() => ({ data: [] })), api.get("/equipment").catch(() => ({ data: [] })), api.get("/work-templates").catch(() => ({ data: [] })), api.get("/work-recurrences").catch(() => ({ data: [] })),
  ]).then(([t, e, w, v, p, tp, rc]) => setRef({ team: (t.data || []).filter((x) => x.active !== false), events: (e.data || []).filter((x) => x.status !== "cloture"), warehouses: w.data || [], vehicles: v.data || [],
    products: (Array.isArray(p.data) ? p.data : p.data?.items || []).map((x) => ({ id: x.id, name: x.name })), templates: tp.data || [], recurrences: rc.data || [] })), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadRef(); }, [loadRef]);
  const ctx = useMemo(() => ({ ...ref, types: d?.types || [], siblings }), [ref, d, siblings]);
  const onSaved = (x) => { if (x?.openStep) { setSiblings(x.siblings); setEdit(x.openStep); return; } setSiblings(null); load(); };
  if (!d) return <Loading />;
  const rows = d.orders.filter((w) => !type || w.type === type);
  const pill = (on) => `rounded-full px-4 py-1.5 text-xs font-semibold transition-colors ${on ? "bg-foreground text-background" : "text-muted-foreground"}`;
  const TABS = [["backlog", "À planifier"], ["planned", "Planifiés"], ["done", "Terminés"], ...(write ? [["templates", "Modèles"], ["recurrences", "Récurrences"]] : [])];
  return (
    <div data-testid="works-page">
      <PageHeader title="Travaux internes" subtitle="Construction, rangement d'entrepôt, inventaires, réparations, atelier retour, entretien des véhicules : le travail des équipes hors événements."
        actions={write && <Button onClick={() => { setSiblings(null); setEdit({}); }} data-testid="new-work-button"><Plus />Travail</Button>} />
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="flex rounded-full border border-border bg-card p-1">{TABS.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={pill(tab === k)} data-testid={`works-tab-${k}`}>{l}</button>)}</div>
        {!["templates", "recurrences"].includes(tab) && <select className="h-9 rounded-full border border-border bg-card px-3 text-xs" value={type} onChange={(e) => setType(e.target.value)} data-testid="works-type-filter">
          <option value="">Tous les types</option>{d.types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</select>}
        {tab === "backlog" && <span className="flex items-center gap-1 text-sm text-muted-foreground"><Layers className="h-4 w-4" />{rows.length} travail(aux) à planifier, du plus urgent au moins urgent</span>}
      </div>
      {tab === "templates" ? <Templates ctx={ctx} reload={loadRef} /> : tab === "recurrences" ? <Recurrences ctx={ctx} reload={() => { loadRef(); load(); }} /> : (
        <div className="space-y-2">{rows.length ? rows.map((w) => <Row key={w.id} w={w} ctx={ctx} onOpen={(x) => { setSiblings(null); setEdit(x); }} />) : <p className="text-sm text-muted-foreground">Rien ici.</p>}</div>)}
      <WorkDialog work={edit} ctx={ctx} onClose={() => { setEdit(null); setSiblings(null); }} onSaved={onSaved} />
    </div>
  );
}
