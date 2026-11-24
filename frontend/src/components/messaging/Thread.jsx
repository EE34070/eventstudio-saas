import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Archive, ArchiveRestore, ArrowLeft, MailOpen, Mail, Paperclip, Send, ShieldAlert, Sparkles, Star, Trash2, Undo2 } from "lucide-react";
import { LabelPicker } from "@/components/messaging/Labels";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Loading } from "@/components/common";
import { api, downloadPdf, errMsg } from "@/lib/api";
import { fmtDT } from "@/lib/constants";

const csp = (img) => `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${img ? "https: data:" : "data:"}; style-src 'unsafe-inline'"><base target="_blank">`;

function HtmlBody({ html }) {
  const ref = useRef(null);
  const [img, setImg] = useState(false);
  const fit = () => { const d = ref.current?.contentDocument; if (d?.body) ref.current.style.height = `${Math.min(d.documentElement.scrollHeight + 8, 1400)}px`; };
  return (<>
    {!img && /<img\b/i.test(html) && <button type="button" className="mb-1 text-xs underline" onClick={() => setImg(true)} data-testid="show-images-button">Afficher les images distantes</button>}
    <iframe key={img ? "i" : "n"} ref={ref} title="Contenu du message" sandbox="allow-same-origin allow-popups" onLoad={fit} className="w-full rounded-lg bg-white" style={{ height: 120 }}
      srcDoc={`${csp(img)}<body style="font-family:Arial,sans-serif;font-size:14px;margin:8px;word-break:break-word">${html}</body>`} /></>);
}

function MessageCard({ m }) {
  const out = m.direction === "out";
  return (
    <div className={`rounded-2xl border border-border p-4 ${out ? "bg-secondary/50" : "bg-card"}`} data-testid={`message-${m.id}`}>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="text-sm font-semibold">{out ? "Vous" : m.from.name || m.from.email}</span>
        <span className="text-xs text-muted-foreground">{out ? `à ${m.to.join(", ")}` : m.from.email}</span>
        <span className="ml-auto text-xs text-muted-foreground">{fmtDT(new Date(m.sent_at).toLocaleString("sv-SE").replace(" ", "T"))}</span>
      </div>
      {m.html ? <HtmlBody html={m.html} /> : <p className="whitespace-pre-wrap break-words text-sm">{m.text}</p>}
      {m.attachments?.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {m.attachments.map((a, i) => (
            <button key={i} type="button" data-testid={`attachment-${m.id}-${i}`}
              onClick={() => downloadPdf(`/messaging/messages/${m.id}/attachments/${i}`, a.filename).catch((e) => toast.error(errMsg(e)))}
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs hover:bg-secondary">
              <Paperclip className="h-3 w-3 shrink-0" /><span className="truncate">{a.filename}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export const Thread = ({ conv, selected, status, write, onBack, onChanged, setConv }) => {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState("");
  const end = useRef(null);
  const id = conv?.id;
  useEffect(() => { setText(""); }, [id]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [id, conv?.messages?.length]);
  useEffect(() => {
    if (id && conv.unread && write && !conv.deleted_at) api.patch(`/messaging/conversations/${id}`, { unread: false }).then(onChanged).catch(() => {});
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!selected) return <div className="card-soft flex h-full items-center justify-center p-8 text-sm text-muted-foreground" data-testid="thread-empty">Sélectionnez une conversation.</div>;
  if (!conv) return <div className="card-soft h-full"><Loading /></div>;

  const run = async (key, fn, ok) => {
    setBusy(key);
    try { await fn(); if (ok) toast.success(ok); } catch (e) { toast.error(errMsg(e)); }
    setBusy("");
  };
  const patch = (body, ok, close) => run("patch", async () => { await api.patch(`/messaging/conversations/${id}`, body); onChanged(); if (close) onBack(); }, ok);
  const trash = () => run("trash", async () => { await api.delete(`/messaging/conversations/${id}`); onChanged(); onBack(); }, `Placée dans la corbeille pour ${status.trash_days} jours`);
  const restore = () => run("trash", async () => { await api.post(`/messaging/conversations/${id}/restore`); onChanged(); }, "Conversation restaurée");
  const suggest = () => run("suggest", async () => { const r = await api.post(`/messaging/conversations/${id}/suggest`); setText(r.data.text); });
  const send = () => run("send", async () => { const r = await api.post(`/messaging/conversations/${id}/reply`, { text }); setConv(r.data); setText(""); onChanged(); }, "Réponse envoyée");

  return (
    <div className="card-soft flex h-full flex-col overflow-hidden" data-testid="thread-panel">
      <div className="flex items-center gap-1 border-b border-border p-3">
        <button className="icon-btn lg:hidden" onClick={onBack} aria-label="Retour" data-testid="thread-back-button"><ArrowLeft className="h-5 w-5" /></button>
        <h2 className="min-w-0 flex-1 truncate px-1 text-base font-semibold" data-testid="thread-subject">{conv.subject}</h2>
        {write && (conv.deleted_at ? (
          <Button size="sm" variant="outline" onClick={restore} disabled={!!busy} data-testid="thread-restore-button"><Undo2 />Restaurer</Button>
        ) : (<>
          <button className="icon-btn" title={conv.unread ? "Marquer comme lu" : "Marquer comme non lu"} disabled={!!busy} onClick={() => patch({ unread: !conv.unread })} data-testid="thread-unread-button">{conv.unread ? <MailOpen className="h-[18px] w-[18px]" /> : <Mail className="h-[18px] w-[18px]" />}</button>
          {conv.box !== "sent" && <button className="icon-btn" title={conv.box === "inbox" ? "Archiver" : "Remettre en réception"} disabled={!!busy} onClick={() => patch({ archived: conv.box === "inbox" }, conv.box === "inbox" ? "Conversation archivée" : "Remise en réception", conv.box === "inbox")} data-testid="thread-archive-button">{conv.box === "inbox" ? <Archive className="h-[18px] w-[18px]" /> : <ArchiveRestore className="h-[18px] w-[18px]" />}</button>}
          <button className="icon-btn" title={conv.is_starred ? "Ne plus suivre" : "Suivre"} disabled={!!busy} onClick={() => patch({ starred: !conv.is_starred })} data-testid="thread-star-button"><Star className={`h-[18px] w-[18px] ${conv.is_starred ? "fill-amber-400 text-amber-500" : ""}`} /></button>
          <button className="icon-btn" title={conv.is_spam ? "Ce n'est pas du spam" : "Signaler comme spam"} disabled={!!busy} onClick={() => patch({ spam: !conv.is_spam }, conv.is_spam ? "Remise en réception" : "Signalée comme spam", !conv.is_spam)} data-testid="thread-spam-button"><ShieldAlert className="h-[18px] w-[18px]" /></button>
          <LabelPicker labels={status.labels} disabled={!!busy} testid="thread-label" onPick={(lid, archive) => run("patch", async () => { await api.post("/messaging/conversations/bulk", { ids: [id], add_label_ids: [lid], archive }); onChanged(); if (archive) onBack(); }, archive ? "Classée et archivée" : "Classée")} />
          <button className="icon-btn" title="Mettre à la corbeille" disabled={!!busy} onClick={trash} data-testid="thread-trash-button"><Trash2 className="h-[18px] w-[18px]" /></button>
        </>))}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-4 py-2 text-xs" data-testid="thread-labels">
        {!conv.contact_id && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-amber-700" data-testid="thread-unlinked">Non rattachée à un contact</span>}
        {conv.gmail_category && conv.gmail_category !== "primary" && <span className="rounded-full border border-border px-2 py-0.5">{status.gmail_categories[conv.gmail_category]}</span>}
        {(conv.label_ids || []).map((g) => { const l = status.labels.find((x) => x.gmail_id === g); return l ? <span key={g} className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5" data-testid={`thread-label-chip-${l.id}`}>{l.name}{write && <button aria-label="Retirer" onClick={() => run("patch", async () => { await api.post("/messaging/conversations/bulk", { ids: [id], remove_label_ids: [g] }); onChanged(); })}>×</button>}</span> : null; })}
      </div>
      <div className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto p-4" data-testid="thread-messages">
        {conv.messages.map((m) => <MessageCard key={m.id} m={m} />)}
        <div ref={end} />
      </div>
      {write && conv.can_reply && (
        <div className="border-t border-border p-3" data-testid="reply-composer">
          <Textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder={`Répondre à ${conv.counterpart?.email || "…"}`} data-testid="reply-textarea" />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {status.configured.ai && <Button size="sm" variant="outline" onClick={suggest} disabled={!!busy} data-testid="reply-suggest-button"><Sparkles />{busy === "suggest" ? "Rédaction…" : "Suggérer une réponse"}</Button>}
            <span className="text-xs text-muted-foreground">La suggestion reste un brouillon : rien ne part sans votre clic.</span>
            <Button size="sm" className="ml-auto" onClick={send} disabled={!!busy || !text.trim()} data-testid="reply-send-button"><Send />{busy === "send" ? "Envoi…" : "Envoyer"}</Button>
          </div>
        </div>
      )}
    </div>
  );
};
