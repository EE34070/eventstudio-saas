import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Section } from "@/components/common";
import { UploadButton, openFile } from "@/lib/files";
import { TranslateButton, langLabel } from "@/lib/i18n";
import { api, errMsg } from "@/lib/api";
import { useMe } from "@/context/MeContext";
import { fmtDate } from "@/lib/constants";

const STATUS = { none: "Non invité", invited: "Invité", active: "Actif", suspended: "Suspendu", deleted: "Accès supprimé" };
const MSTATUS = { confirmed: "Confirmée", done: "Réalisée", invoiced: "Facturée", paid: "Payée", cancelled: "Annulée" };
const STATE = { active: "Espace ouvert", read_only: "Lecture seule", disabled: "Désactivé" };

export default function PortalTab({ ev }) {
  const { can } = useMe();
  const write = can("events:write");
  const [d, setD] = useState(null);
  const [items, setItems] = useState([]);
  const [msg, setMsg] = useState("");
  const [links, setLinks] = useState({});
  const load = useCallback(() => api.get(`/events/${ev.id}/portal`).then((r) => { setD(r.data); setItems(r.data.timeline.items); }).catch((e) => toast.error(errMsg(e))), [ev.id]);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const run = async (fn, ok) => { try { const r = await fn(); if (ok) toast.success(ok); load(); return r; } catch (e) { toast.error(errMsg(e)); return null; } };
  const invite = async (ids) => {
    const r = await run(() => api.post(`/events/${ev.id}/portal/invite`, { contact_ids: ids }));
    if (!r) return;
    r.data.forEach((x) => (x.error ? toast.error(typeof x.error === "string" ? x.error : "Invitation impossible") : x.sent ? toast.success(`Invitation envoyée à ${x.email}`) : setLinks((l) => ({ ...l, [x.contact_id]: x.link }))));
  };
  const userAct = (uid, a, ok) => run(() => api.post(`/portal-users/${uid}/${a}`), ok);
  const Person = ({ c }) => (
    <div className="flex flex-wrap items-center gap-2 border-b border-border py-2.5 text-sm last:border-0" data-testid={`portal-client-${c.contact_id}`}>
      <div className="min-w-0 flex-1"><b>{c.name}</b>{c.organizer && <span className="ml-2 text-xs text-muted-foreground">Organisateur · lecture seule</span>}<div className="text-xs text-muted-foreground">{c.email || "pas d'e-mail"} · {langLabel(c.language)}{c.last_login_at ? ` · dernière connexion ${fmtDate(c.last_login_at)}` : ""}</div>
        {links[c.contact_id] && <div className="mt-1 break-all rounded-lg bg-amber-500/10 p-2 text-xs text-amber-700" data-testid="portal-invite-link">E-mail non envoyé (boîte Gmail non connectée ou adresse de test). Lien à transmettre : {links[c.contact_id]}</div>}</div>
      <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold" data-testid={`portal-status-${c.contact_id}`}>{STATUS[c.status]}</span>
      {write && <Button size="sm" variant="outline" onClick={() => invite([c.contact_id])} data-testid={`portal-invite-${c.contact_id}`}>{c.status === "none" ? "Inviter" : "Renvoyer"}</Button>}
      {can("users:manage") && c.user_id && <>
        {c.status === "suspended" ? <Button size="sm" variant="ghost" onClick={() => userAct(c.user_id, "reactivate", "Accès réactivé")}>Réactiver</Button> : <Button size="sm" variant="ghost" onClick={() => userAct(c.user_id, "suspend", "Accès suspendu")}>Suspendre</Button>}
        <Button size="sm" variant="ghost" onClick={() => userAct(c.user_id, "revoke", "Sessions révoquées")}>Révoquer les sessions</Button>
        <Button size="sm" variant="ghost" onClick={() => window.confirm("Supprimer l'accès ? Le contact est conservé.") && userAct(c.user_id, "delete", "Accès supprimé")}>Supprimer l'accès</Button>
        <a className="text-xs font-semibold underline" href={`/apercu/${c.user_id}`} target="_blank" rel="noreferrer" data-testid={`portal-view-as-${c.contact_id}`}>Voir comme le client</a></>}
    </div>
  );
  const upItem = (i, k, v) => setItems(items.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  return (
    <div className="space-y-6" data-testid="portal-tab">
      <Section title="Espace client" testid="portal-clients" actions={<div className="flex items-center gap-3"><span className="text-xs text-muted-foreground">{STATE[d.state]}</span>{write && d.clients.length > 1 && <Button size="sm" onClick={() => invite([])} data-testid="portal-invite-all">Inviter tous les clients</Button>}</div>}>
        {!d.clients.length && <p className="text-sm text-muted-foreground">Aucun client sur cet événement.</p>}
        {d.clients.map((c) => <Person key={c.contact_id} c={c} />)}
        {d.organizer && <><label className="mt-3 flex items-center gap-2 text-sm"><Switch disabled={!write} checked={d.organizer_portal_access} onCheckedChange={(v) => run(() => api.patch(`/events/${ev.id}/portal`, { organizer_portal_access: v }))} data-testid="portal-organizer-switch" />Inviter l'organisateur dans l'espace client (lecture seule)</label>{d.organizer_portal_access && <Person c={d.organizer} />}</>}
      </Section>
      <Section title="Modules de l'espace client" testid="portal-modules">
        <p className="mb-2 text-xs text-muted-foreground">Masquer un module ne supprime jamais ses données.</p>
        {d.modules.map((m) => { const put = (ch) => run(() => api.put(`/events/${ev.id}/portal/modules/${m.module_key}`, { client_visible: m.client_visible, client_editable: m.client_editable, visible_from: m.visible_from || "", lock_date: m.lock_date || "", ...ch })); return (
          <div key={m.module_key} className="flex flex-wrap items-center gap-4 border-b border-border py-2.5 text-sm last:border-0" data-testid={`portal-module-${m.module_key}`}>
            <b className="w-40">{m.label}{!m.built && <span className="ml-1 text-xs font-normal text-muted-foreground">(à venir)</span>}{!m.active && <span className="ml-1 text-xs font-normal text-amber-700">(désactivé)</span>}</b>
            <label className="flex items-center gap-2"><Switch disabled={!write} checked={m.client_visible} onCheckedChange={(v) => put({ client_visible: v })} data-testid={`portal-module-visible-${m.module_key}`} />Visible</label>
            <label className="flex items-center gap-2"><Switch disabled={!write} checked={m.client_editable} onCheckedChange={(v) => put({ client_editable: v })} />Modifiable</label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">Verrouillage<Input type="date" disabled={!write} className="h-8 w-40" defaultValue={m.lock_date || ""} onBlur={(e) => e.target.value !== (m.lock_date || "") && put({ lock_date: e.target.value })} /></label>
          </div>); })}
      </Section>
      <Section title="Déroulé" testid="portal-timeline" actions={write && <div className="flex gap-2"><TranslateButton testid="timeline-translate" texts={Object.fromEntries(items.filter((x) => x.label).map((x, i) => [`i${i}`, x.label]))} context="Étapes du déroulé d'un événement." onDone={(r) => setItems(items.filter((x) => x.label).map((x, i) => ({ ...x, label_en: r[`i${i}`] || x.label_en })))} />
        <Button size="sm" variant="outline" onClick={() => setItems([...items, { id: "", time: "", label: "", label_en: "", description: "", description_en: "" }])} data-testid="timeline-add"><Plus />Étape</Button></div>}>
        {items.map((x, i) => <div key={i} className="mb-2 grid grid-cols-12 gap-2" data-testid={`timeline-row-${i}`}><Input type="time" className="col-span-2 h-9" value={x.time} onChange={(e) => upItem(i, "time", e.target.value)} /><Input className="col-span-4 h-9" placeholder="Étape *" value={x.label} onChange={(e) => upItem(i, "label", e.target.value)} data-testid={`timeline-label-${i}`} />
          <Input className="col-span-3 h-9" placeholder="English" value={x.label_en} onChange={(e) => upItem(i, "label_en", e.target.value)} /><Input className="col-span-2 h-9" placeholder="Détail" value={x.description} onChange={(e) => upItem(i, "description", e.target.value)} /><button aria-label="Supprimer" onClick={() => setItems(items.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button></div>)}
        {write && <Button size="sm" onClick={() => run(() => api.put(`/events/${ev.id}/timeline`, { items: items.filter((x) => x.label.trim()) }), "Déroulé enregistré")} data-testid="timeline-save">Enregistrer le déroulé</Button>}
        {d.timeline.comments.length > 0 && <div className="mt-3 text-sm"><div className="eyebrow">Commentaires du client</div>{d.timeline.comments.map((c) => <div key={c.id}>{c.by} : {c.body}</div>)}</div>}
      </Section>
      <Section title="Documents partagés avec le client" testid="portal-documents" actions={write && <UploadButton accept="application/pdf,image/*" multiple={false} label="Partager un document" testid="portal-doc-upload" onUploaded={(r) => { const title = window.prompt("Titre du document", "Contrat"); if (title) run(() => api.post(`/events/${ev.id}/client-documents`, { file_ref: r[0], title }), "Document partagé"); }} />}>
        <p className="mb-2 text-xs text-muted-foreground">Les fiches « Partageable client » du matériel réservé sont ajoutées automatiquement. Les documents internes ne sont jamais visibles.</p>
        {d.documents.map((x) => <div key={x.id} className="flex items-center gap-3 border-b border-border py-2 text-sm last:border-0"><span className="flex-1">{x.title}</span><button className="underline" onClick={() => openFile(x.file_ref)}>Ouvrir</button>
          <label className="flex items-center gap-2"><Switch disabled={!write} checked={x.visible_to_client} onCheckedChange={(v) => run(() => api.patch(`/client-documents/${x.id}`, { visible_to_client: v }))} />Visible</label>{write && <button aria-label="Retirer" onClick={() => run(() => api.delete(`/client-documents/${x.id}`), "Document retiré")}><Trash2 className="h-4 w-4" /></button>}</div>)}
      </Section>
      <Section title="Messages du portail" testid="portal-messages">
        {!d.messages.length && <p className="text-sm text-muted-foreground">Aucun message.</p>}
        {d.messages.map((m) => <div key={m.id} className="border-b border-border py-2 text-sm last:border-0"><b>{m.from_name}</b> <span className="text-xs text-muted-foreground">{m.thread === "client" ? "client" : "prestataire"} · {fmtDate(m.at)}</span><div className="whitespace-pre-wrap">{m.body}</div></div>)}
        {write && <div className="mt-2 flex gap-2"><Input value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Répondre au client…" data-testid="portal-reply-input" /><Button disabled={!msg.trim()} onClick={() => run(() => api.post(`/events/${ev.id}/portal/messages`, { body: msg, thread: "client" }), "Message envoyé").then(() => setMsg(""))} data-testid="portal-reply-send">Envoyer</Button></div>}
      </Section>
      {can("providers:manage") && <Section title="Équipe prestataires" testid="portal-missions">
        {!d.missions.length && <p className="text-sm text-muted-foreground">Aucun prestataire retenu sur cet événement.</p>}
        {d.missions.map((m) => { const patch = (ch, ok) => run(() => api.patch(`/missions/${m.id}`, ch), ok); return (
          <div key={m.id} className="flex flex-wrap items-center gap-3 border-b border-border py-2.5 text-sm last:border-0" data-testid={`portal-mission-${m.id}`}><b className="min-w-0 flex-1">{m.provider_name}</b><span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold">{MSTATUS[m.status]}</span>{m.presence_confirmed_at && <span className="text-xs text-emerald-700">Présence confirmée</span>}
            <label className="flex items-center gap-2 text-xs"><Switch checked={!!m.share_full_timeline} onCheckedChange={(v) => patch({ share_full_timeline: v })} />Déroulé complet</label><label className="flex items-center gap-2 text-xs"><Switch checked={!!m.share_team} onCheckedChange={(v) => patch({ share_team: v })} />Partager l'équipe</label>
            {m.provider_invoice_file && <button className="underline" onClick={() => openFile(m.provider_invoice_file)} data-testid={`mission-invoice-${m.id}`}>Facture PDF</button>}
            {m.status !== "cancelled" && <Button size="sm" variant="ghost" onClick={() => window.confirm("Annuler cette mission ? Le prestataire perd immédiatement l'accès.") && patch({ status: "cancelled" }, "Mission annulée")} data-testid={`mission-cancel-${m.id}`}>Annuler la mission</Button>}</div>); })}
      </Section>}
    </div>
  );
}
