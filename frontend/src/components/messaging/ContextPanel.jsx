import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CalendarPlus, Sparkles, Trash2, UserPlus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { EventFromDialog } from "@/components/messaging/MessagingDialogs";

const Block = ({ title, children, testid }) => (
  <div className="border-b border-border p-4 last:border-b-0" data-testid={testid}>
    <div className="eyebrow mb-2">{title}</div>
    {children}
  </div>
);

function ContactPicker({ onPick }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  useEffect(() => {
    if (q.trim().length < 2) { setRows([]); return undefined; }
    const t = setTimeout(() => api.get("/contacts", { params: { q } }).then((r) => setRows(r.data.slice(0, 6))).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="mt-2">
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rattacher un contact existant…" className="h-8 text-xs" data-testid="context-contact-search" />
      {rows.map((c) => (
        <button key={c.id} type="button" onClick={() => onPick(c.id)} className="mt-1 block w-full truncate rounded-lg px-2 py-1.5 text-left text-xs hover:bg-secondary" data-testid={`context-contact-option-${c.id}`}>
          {c.display_name} <span className="text-muted-foreground">{c.email}</span>
        </button>
      ))}
    </div>
  );
}

export const ContextPanel = ({ conv, status, write, setConv, onChanged }) => {
  const { can } = useMe();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [eventDialog, setEventDialog] = useState(false);
  const id = conv.id;
  const run = async (key, fn, ok) => {
    setBusy(key);
    try { const r = await fn(); if (r?.data?.id === id) setConv(r.data); onChanged(); if (ok) toast.success(ok); } catch (e) { toast.error(errMsg(e)); }
    setBusy("");
  };
  const patch = (body, ok) => run("patch", () => api.patch(`/messaging/conversations/${id}`, body), ok);
  const addNote = () => run("note", async () => { await api.post(`/messaging/conversations/${id}/notes`, { text: note }); setNote(""); });
  const editable = write && !conv.deleted_at;

  return (
    <div className="card-soft scroll-thin h-full overflow-y-auto" data-testid="context-panel">
      <Block title="Contact" testid="context-contact">
        {conv.contact ? (
          <div>
            <div className="flex items-start gap-2">
              <Link to={`/contacts?q=${encodeURIComponent(conv.contact.email || "")}`} className="min-w-0 flex-1 truncate text-sm font-semibold hover:underline" data-testid="context-contact-name">{conv.contact.display_name}</Link>
              {editable && <button className="text-muted-foreground hover:text-foreground" title="Détacher le contact" onClick={() => patch({ contact_id: "" })} data-testid="context-contact-unlink"><X className="h-4 w-4" /></button>}
            </div>
            {conv.person_name && <div className="truncate text-xs font-medium" data-testid="context-person-name">{conv.person_name}</div>}
            <div className="truncate text-xs text-muted-foreground">{conv.contact.email}</div>
            {conv.contact.phone && <div className="text-xs text-muted-foreground">{conv.contact.phone}</div>}
          </div>
        ) : (
          <div>
            <div className="truncate text-sm">{conv.counterpart?.name || conv.counterpart?.email}</div>
            <div className="truncate text-xs text-muted-foreground">{conv.counterpart?.email} — adresse inconnue des contacts</div>
            {editable && can("contacts:write") && <Button size="sm" variant="outline" className="mt-2" disabled={!!busy} onClick={() => run("contact", () => api.post(`/messaging/conversations/${id}/contact`), "Contact créé")} data-testid="context-create-contact"><UserPlus />Créer le contact</Button>}
            {editable && <ContactPicker onPick={(cid) => patch({ contact_id: cid }, "Contact rattaché")} />}
          </div>
        )}
      </Block>
      <Block title="Événement lié" testid="context-event">
        {conv.event ? (
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <Link to={`/evenements/${conv.event.id}`} className="block truncate text-sm font-semibold hover:underline" data-testid="context-event-title">{conv.event.title}</Link>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">{fmtDate(conv.event.start)}<StatusBadge status={conv.event.status} /></div>
            </div>
            {editable && <button className="text-muted-foreground hover:text-foreground" title="Détacher l'événement" onClick={() => patch({ event_id: "" })} data-testid="context-event-unlink"><X className="h-4 w-4" /></button>}
          </div>
        ) : <p className="text-sm text-muted-foreground">Aucun événement rattaché.</p>}
        {editable && conv.contact_events.length > 0 && (
          <Select value={conv.event?.id || ""} onValueChange={(v) => patch({ event_id: v }, "Événement rattaché")}>
            <SelectTrigger className="mt-2 h-8 text-xs" data-testid="context-event-select"><SelectValue placeholder="Choisir un événement du contact" /></SelectTrigger>
            <SelectContent>{conv.contact_events.map((e) => <SelectItem key={e.id} value={e.id}>{e.title} — {fmtDate(e.start)}</SelectItem>)}</SelectContent>
          </Select>
        )}
        {editable && can("events:write") && <Button size="sm" variant="outline" className="mt-2" onClick={() => setEventDialog(true)} data-testid="context-create-event"><CalendarPlus />Créer l'événement depuis cette conversation</Button>}
      </Block>
      <Block title="Classement" testid="context-classification">
        <Select value={conv.category || ""} onValueChange={(v) => patch({ category: v })} disabled={!editable}>
          <SelectTrigger className="h-8 text-xs" data-testid="context-category-select"><SelectValue placeholder="Non classée" /></SelectTrigger>
          <SelectContent>{Object.entries(status.categories).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent>
        </Select>
        {conv.ai_summary && <p className="mt-2 text-sm" data-testid="context-ai-summary">{conv.ai_summary}</p>}
        {conv.classified_at && <p className="mt-1 text-xs text-muted-foreground">{conv.needs_reply ? "Réponse attendue" : "Pas de réponse attendue"} — analyse automatique, à vérifier.</p>}
        {editable && status.configured.ai && <Button size="sm" variant="outline" className="mt-2" disabled={!!busy} onClick={() => run("classify", () => api.post(`/messaging/conversations/${id}/classify`))} data-testid="context-classify-button"><Sparkles />{busy === "classify" ? "Analyse…" : "Analyser"}</Button>}
        {!status.configured.ai && <p className="mt-2 text-xs text-muted-foreground">Assistant IA non configuré.</p>}
      </Block>
      <Block title="Notes internes" testid="context-notes">
        {conv.notes.map((n) => (
          <div key={n.id} className="mb-2 rounded-xl bg-amber-500/10 p-2.5 text-sm" data-testid={`note-${n.id}`}>
            <div className="whitespace-pre-wrap break-words">{n.text}</div>
            <div className="mt-1 flex items-center text-[11px] text-muted-foreground">{n.by} · {fmtDate(n.created_at)}
              {write && <button className="ml-auto hover:text-foreground" title="Supprimer la note" onClick={() => run("note", () => api.delete(`/messaging/notes/${n.id}`))} data-testid={`note-delete-${n.id}`}><Trash2 className="h-3.5 w-3.5" /></button>}
            </div>
          </div>
        ))}
        {write && (<>
          <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note visible par l'équipe uniquement" className="text-sm" data-testid="note-textarea" />
          <Button size="sm" className="mt-2" disabled={!!busy || !note.trim()} onClick={addNote} data-testid="note-add-button">Ajouter la note</Button>
        </>)}
      </Block>
      <EventFromDialog open={eventDialog} onOpenChange={setEventDialog} convId={id} onCreated={onChanged} />
    </div>
  );
};
