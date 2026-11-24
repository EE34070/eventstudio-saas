import { useCallback, useEffect, useState } from "react";
import { TrashBtn } from "@/components/Trash";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Sparkles, Trash2, Paperclip } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { PageHeader, Loading, Field } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { UploadButton, openFile } from "@/lib/files";
import { fmtDate } from "@/lib/constants";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm";
const PRIO = { low: ["Basse", "bg-secondary text-muted-foreground"], normal: ["Normale", "bg-secondary"], high: ["Haute", "bg-amber-500/15 text-amber-700 dark:text-amber-300"], urgent: ["Urgente", "bg-red-500/15 text-red-600"] };
const STATUS = [["todo", "À faire"], ["doing", "En cours"], ["done", "Fait"]];
const EMPTY = { title: "", description: "", due_at: "", priority: "normal", assignee_ids: [], event_id: "", status: "todo", checklist: [], attachments: [] };

function TaskDialog({ task, people, events, onClose, onSaved }) {
  const [f, setF] = useState(EMPTY);
  const [item, setItem] = useState("");
  useEffect(() => { if (task) setF({ ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).map((k) => [k, task[k] ?? EMPTY[k]])) }); }, [task]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const [d, t] = [f.due_at.slice(0, 10), f.due_at.slice(11, 16)];
  const due = (nd, nt) => setF({ ...f, due_at: nd ? (nt ? `${nd}T${nt}` : nd) : "" });
  const submit = (e) => { e.preventDefault(); (task.id ? api.patch(`/tasks/${task.id}`, f) : api.post("/tasks", f)).then(() => { toast.success("Tâche enregistrée"); onSaved(); onClose(); }).catch(ko); };
  return (
    <Dialog open={!!task} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{task?.id ? "Modifier la tâche" : "Nouvelle tâche"}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-4" data-testid="task-form">
          <Field label="Titre" className="col-span-2"><Input required value={f.title} onChange={set("title")} data-testid="task-title-input" /></Field>
          <Field label="Description" className="col-span-2"><Textarea rows={3} value={f.description} onChange={set("description")} data-testid="task-description-input" /></Field>
          <Field label="Échéance"><Input type="date" value={d} onChange={(e) => due(e.target.value, t)} data-testid="task-due-date" /></Field>
          <Field label="Heure (facultatif)"><Input type="time" value={t} disabled={!d} onChange={(e) => due(d, e.target.value)} data-testid="task-due-time" /></Field>
          <Field label="Priorité"><select className={sel} value={f.priority} onChange={set("priority")} data-testid="task-priority">{Object.entries(PRIO).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Statut"><select className={sel} value={f.status} onChange={set("status")} data-testid="task-status">{STATUS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Événement lié" className="col-span-2"><select className={sel} value={f.event_id} onChange={set("event_id")} data-testid="task-event"><option value="">Aucun</option>{events.map((e) => <option key={e.id} value={e.id}>{e.code} · {e.title}</option>)}</select></Field>
          <div className="col-span-2"><div className="mb-1.5 text-xs font-medium text-muted-foreground">Assignée à</div>
            <div className="flex flex-wrap gap-1.5">{people.map((p) => { const on = f.assignee_ids.includes(p.id); return <button type="button" key={p.id} aria-pressed={on} onClick={() => setF({ ...f, assignee_ids: on ? f.assignee_ids.filter((x) => x !== p.id) : [...f.assignee_ids, p.id] })} data-testid={`task-assignee-${p.id}`} className={`rounded-full border px-3 py-1 text-xs ${on ? "border-primary bg-primary text-white" : "border-border"}`}>{p.name}</button>; })}</div></div>
          <div className="col-span-2"><div className="mb-1.5 text-xs font-medium text-muted-foreground">Check-list</div>
            {f.checklist.map((c, i) => <label key={i} className="mb-1 flex items-center gap-2 text-sm"><input type="checkbox" checked={c.done} onChange={(e) => setF({ ...f, checklist: f.checklist.map((x, j) => (j === i ? { ...x, done: e.target.checked } : x)) })} /><span className={`flex-1 ${c.done ? "text-muted-foreground line-through" : ""}`}>{c.text}</span><button type="button" onClick={() => setF({ ...f, checklist: f.checklist.filter((_, j) => j !== i) })} aria-label="Retirer"><Trash2 className="h-3.5 w-3.5 text-muted-foreground" /></button></label>)}
            <div className="flex gap-2"><Input value={item} onChange={(e) => setItem(e.target.value)} placeholder="Ajouter un point" data-testid="task-check-input" onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (item.trim()) { setF({ ...f, checklist: [...f.checklist, { text: item.trim(), done: false }] }); setItem(""); } } }} /></div></div>
          <div className="col-span-2 flex flex-wrap items-center gap-2"><UploadButton label="Pièce jointe" testid="task-attach" onUploaded={(refs) => setF({ ...f, attachments: [...f.attachments, ...refs] })} />
            {f.attachments.map((a, i) => <span key={a} className="flex items-center gap-1 rounded-full bg-secondary px-2.5 py-1 text-xs"><button type="button" onClick={() => openFile(a)} className="flex items-center gap-1"><Paperclip className="h-3 w-3" />Fichier {i + 1}</button><button type="button" onClick={() => setF({ ...f, attachments: f.attachments.filter((x) => x !== a) })} aria-label="Retirer">×</button></span>)}</div>
          <DialogFooter className="col-span-2">{task?.id && <Button type="button" variant="outline" onClick={() => api.post(`/tasks/${task.id}/to-work-order`).then(() => { toast.success("Transformée en travail interne à planifier"); onSaved(); onClose(); }).catch(ko)} data-testid="task-to-work">Travail planifiable</Button>}{task?.id && <Button type="button" variant="ghost" onClick={() => api.delete(`/tasks/${task.id}`).then(() => { onSaved(); onClose(); }).catch(ko)} data-testid="task-delete"><Trash2 />Supprimer</Button>}<Button data-testid="task-form-submit">Enregistrer</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Card({ t, today, people, onOpen, onStatus, draggable, reload }) {
  const late = t.status !== "done" && t.due_at && t.due_at < today;
  const names = t.assignee_ids.map((id) => people.find((p) => p.id === id)?.name).filter(Boolean);
  const checks = t.checklist?.length ? `${t.checklist.filter((c) => c.done).length}/${t.checklist.length}` : "";
  return (
    <div draggable={draggable} onDragStart={(e) => e.dataTransfer.setData("text/plain", t.id)} className="flex items-start gap-3 rounded-xl border border-border bg-card p-3" data-testid={`task-${t.id}`}>
      <input type="checkbox" className="mt-1 h-4 w-4" checked={t.status === "done"} onChange={(e) => onStatus(t, e.target.checked ? "done" : "todo")} aria-label="Fait" data-testid={`task-done-${t.id}`} />
      <button className="min-w-0 flex-1 text-left" onClick={() => onOpen(t)} data-testid={`task-open-${t.id}`}>
        <div className={`text-sm font-medium ${t.status === "done" ? "text-muted-foreground line-through" : ""}`}>{t.title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {t.due_at && <span className={late ? "font-semibold text-red-600" : ""} data-testid={late ? `task-late-${t.id}` : undefined}>{fmtDate(t.due_at.slice(0, 10), { day: "numeric", month: "short" })}{t.due_at.length > 10 ? ` · ${t.due_at.slice(11, 16)}` : ""}</span>}
          <span className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${PRIO[t.priority]?.[1]}`}>{PRIO[t.priority]?.[0]}</span>
          {t.source === "auto" && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10.5px] font-semibold text-primary" data-testid={`task-auto-${t.id}`}>auto</span>}
          {t.source === "crm" && <span className="rounded-full bg-secondary px-2 py-0.5 text-[10.5px] font-semibold">CRM</span>}
          {checks && <span>{checks}</span>}{names.length > 0 && <span>{names.join(", ")}</span>}
        </div>
      </button>
      {t.event_id && <Link to={`/evenements/${t.event_id}`} className="max-w-[40%] truncate text-xs text-primary hover:underline">{t.event_title}</Link>}
      <TrashBtn kind="task" id={t.id} name={t.title} onDone={reload} />
    </div>
  );
}

export default function Todo() {
  const [mine, setMine] = useState(false);
  const [view, setView] = useState("list");
  const [d, setD] = useState(null);
  const [events, setEvents] = useState([]);
  const [edit, setEdit] = useState(null);
  const [quick, setQuick] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.get("/tasks", { params: { mine } }).then((r) => setD(r.data)).catch(ko), [mine]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.get("/events").then((r) => setEvents(r.data.filter((e) => e.status !== "cloture"))).catch(() => {}); }, []);
  const onStatus = (t, status) => api.patch(`/tasks/${t.id}`, { status }).then(load).catch(ko);
  const add = (e) => { e.preventDefault(); if (!quick.trim()) return; setBusy(true); api.post("/tasks/quick", { text: quick }).then((r) => { setQuick(""); toast.success(r.data.due_at ? `Tâche ajoutée pour le ${fmtDate(r.data.due_at.slice(0, 10))}${r.data.due_at.length > 10 ? " à " + r.data.due_at.slice(11, 16) : ""}` : "Tâche ajoutée sans échéance"); load(); }).catch(ko).finally(() => setBusy(false)); };
  if (!d) return <Loading />;
  const open = d.tasks.filter((t) => t.status !== "done");
  const groups = [["late", "En retard", open.filter((t) => t.due_at && t.due_at < d.today)], ["today", "Aujourd'hui", open.filter((t) => t.due_at.startsWith(d.today))],
    ["next", "À venir", open.filter((t) => !t.due_at || t.due_at.slice(0, 10) > d.today)], ["done", "Faites", d.tasks.filter((t) => t.status === "done").slice(-30).reverse()]];
  const card = (t, draggable) => <Card key={t.id} t={t} today={d.today} people={d.people} onOpen={setEdit} onStatus={onStatus} draggable={draggable} reload={load} />;
  const pill = (on) => `rounded-full px-4 py-1.5 text-xs font-semibold transition-colors ${on ? "bg-foreground text-background" : "text-muted-foreground"}`;
  return (
    <div data-testid="todo-page">
      <PageHeader title="To do list" subtitle="Tâches de l'équipe, tâches automatiques des événements et relances du CRM, au même endroit."
        actions={<Button onClick={() => setEdit({})} data-testid="new-task-button"><Plus />Tâche</Button>} />
      <form onSubmit={add} className="mb-5 flex gap-2" data-testid="task-quick-form">
        <div className="relative flex-1"><Sparkles className="pointer-events-none absolute left-4 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-primary" /><input className="pill-input" value={quick} onChange={(e) => setQuick(e.target.value)} placeholder="Ajout rapide : « Rappeler le domaine demain 10h »" data-testid="task-quick-input" /></div>
        <Button disabled={busy || !quick.trim()} data-testid="task-quick-submit">{busy ? "Ajout…" : "Ajouter"}</Button>
      </form>
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="flex rounded-full border border-border bg-card p-1">{[["list", "Liste"], ["kanban", "Kanban"]].map(([k, l]) => <button key={k} onClick={() => setView(k)} className={pill(view === k)} data-testid={`todo-view-${k}`}>{l}</button>)}</div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} data-testid="todo-mine" />Mes tâches</label>
        <span className="text-sm text-muted-foreground" data-testid="todo-count">{open.length} tâche(s) ouverte(s)</span>
      </div>
      {view === "list" ? (
        <div className="space-y-6">{groups.map(([k, l, rows]) => (
          <div key={k} data-testid={`todo-group-${k}`}><h2 className={`mb-2 text-base font-semibold md:text-lg ${k === "late" && rows.length ? "text-red-600" : ""}`}>{l} <span className="text-sm font-normal text-muted-foreground">({rows.length})</span></h2>
            <div className="space-y-2">{rows.length ? rows.map((t) => card(t, false)) : <p className="text-sm text-muted-foreground">Rien ici.</p>}</div></div>))}</div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">{STATUS.map(([k, l]) => { const rows = d.tasks.filter((t) => t.status === k); return (
          <div key={k} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { const t = d.tasks.find((x) => x.id === e.dataTransfer.getData("text/plain")); if (t && t.status !== k) onStatus(t, k); }} className="min-h-[200px] rounded-2xl bg-secondary/40 p-3" data-testid={`todo-column-${k}`}>
            <div className="mb-3 px-1 text-sm font-semibold">{l} <span className="font-normal text-muted-foreground">({rows.length})</span></div><div className="space-y-2">{(k === "done" ? rows.slice(-30).reverse() : rows).map((t) => card(t, true))}</div></div>); })}</div>
      )}
      <TaskDialog task={edit} people={d.people} events={events} onClose={() => setEdit(null)} onSaved={load} />
    </div>
  );
}
