import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Copy, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Section } from "@/components/common";
import { FileImg } from "@/lib/files";
import { api } from "@/lib/api";
import { ko, sel, copy, Requests } from "@/components/communication/shared";

export function EventComm({ eid }) {
  const [d, setD] = useState(null);
  const [f, setF] = useState(null);
  const [sending, setSending] = useState(true);
  const load = useCallback(() => api.get(`/communication/events/${eid}`).then((r) => { setD(r.data); setF({ ...r.data.comm, credits: r.data.credits }); }).catch(ko), [eid]);
  useEffect(() => { load(); api.get("/communication/overview").then((r) => setSending(r.data.sending)).catch(() => {}); }, [load]);
  if (!d || !f) return null;
  const w = d.write;
  const save = () => api.put(`/communication/events/${eid}`, { ...f, credits: f.credits.map(({ key, role, name, handle, included }) => ({ key, role, name, handle, included })) }).then((r) => { setD(r.data); setF({ ...r.data.comm, credits: r.data.credits }); toast.success("Enregistré"); }).catch(ko);
  const setC = (i, p) => setF({ ...f, credits: f.credits.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  return (
    <div className="space-y-6" data-testid="event-communication">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Section title="Publication" testid="event-comm-publication">
          <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground">
            <label>Marque<select className={`${sel} mt-1 w-full`} disabled={!w} value={f.brand_id} onChange={(e) => setF({ ...f, brand_id: e.target.value })} data-testid="event-comm-brand"><option value="">—</option>{d.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
            <label>Accord du client pour publier<select className={`${sel} mt-1 w-full`} disabled={!w} value={f.consent} onChange={(e) => setF({ ...f, consent: e.target.value })} data-testid="event-comm-consent"><option value="a_demander">À demander</option><option value="accorde">Accordé</option><option value="refuse">Refusé</option></select></label>
            <label>Embargo jusqu'au<Input className="mt-1 h-9" type="date" disabled={!w} value={f.embargo_date} onChange={(e) => setF({ ...f, embargo_date: e.target.value })} data-testid="event-comm-embargo" /></label>
            <label>Précision sur l'accord<Input className="mt-1 h-9" disabled={!w} value={f.consent_note} onChange={(e) => setF({ ...f, consent_note: e.target.value })} data-testid="event-comm-consent-note" /></label>
            <label className="col-span-2">Notes communication<Input className="mt-1 h-9" disabled={!w} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} data-testid="event-comm-notes" /></label></div>
          <p className="mt-3 text-xs text-muted-foreground">Tant que l'accord n'est pas « Accordé » ou que l'embargo court, les médias de l'événement restent « Bloqués ».</p>
        </Section>
        <Section title={`Médias (${d.media.total})`} testid="event-comm-media" actions={<Link className="text-sm underline" to={`/communication?tab=media&event=${eid}`} data-testid="event-comm-open-media">Ouvrir la médiathèque</Link>}>
          <div className="text-sm" data-testid="event-comm-media-count">{d.media.publiable} publiable(s) sur {d.media.total}</div>
          <div className="mt-2 flex flex-wrap gap-2">{d.media.thumbs.map((t) => <FileImg key={t} src={t} className="h-16 w-16 rounded-lg object-cover" />)}</div>
          {!!d.posts.length && <div className="mt-3 text-xs text-muted-foreground">Publications : {d.posts.map((p) => p.title).join(", ")}</div>}
        </Section>
      </div>
      <Section title="Crédits Instagram" testid="event-comm-credits" actions={<Button size="sm" variant="outline" onClick={() => copy(d.credit_text, "Crédits copiés")} data-testid="event-comm-copy-credits"><Copy />Copier</Button>}>
        {d.missing_handles > 0 && <div className="mb-2 rounded-lg bg-amber-500/10 p-2 text-xs text-amber-700" data-testid="event-comm-missing">{d.missing_handles} intervenant(s) sans identifiant Instagram</div>}
        {f.credits.map((c, i) => (
          <div key={c.key || i} className="flex flex-wrap items-center gap-2 border-b border-border py-1.5 text-sm last:border-0" data-testid={`credit-row-${i}`}>
            <input type="checkbox" disabled={!w} checked={c.included} onChange={(e) => setC(i, { included: e.target.checked })} data-testid={`credit-included-${i}`} />
            <Input className="h-8 w-44" disabled={!w} value={c.role} onChange={(e) => setC(i, { role: e.target.value })} data-testid={`credit-role-${i}`} />
            {c.manual ? <Input className="h-8 w-48" disabled={!w} placeholder="Nom" value={c.name} onChange={(e) => setC(i, { name: e.target.value })} data-testid={`credit-name-${i}`} /> : <span className="w-48 truncate">{c.name}</span>}
            <span>@</span><Input className={`h-8 w-48 ${c.included && !c.handle ? "border-amber-500" : ""}`} disabled={!w} placeholder="identifiant" value={c.handle} onChange={(e) => setC(i, { handle: e.target.value })} data-testid={`credit-handle-${i}`} />
            {w && c.target && c.handle && <button className="text-xs underline" onClick={() => api.put("/communication/handles", { kind: c.target.kind, id: c.target.id, handle: c.handle }).then(() => toast.success("Identifiant enregistré sur la fiche")).catch(ko)} data-testid={`credit-save-contact-${i}`}>enregistrer sur la fiche</button>}
            {w && c.manual && <button aria-label="Retirer" onClick={() => setF({ ...f, credits: f.credits.filter((_, j) => j !== i) })}><Trash2 className="h-4 w-4" /></button>}
          </div>))}
        {w && <Button size="sm" variant="ghost" className="mt-2" onClick={() => setF({ ...f, credits: [...f.credits, { key: "", role: "", name: "", handle: "", included: true, manual: true }] })} data-testid="credit-add"><Plus />Ajouter un intervenant</Button>}
        <pre className="mt-3 whitespace-pre-wrap rounded-lg bg-secondary p-3 text-xs" data-testid="event-comm-credit-text">{d.credit_text || "Aucun crédit avec identifiant."}</pre>
      </Section>
      {w && <div className="flex justify-end"><Button onClick={save} data-testid="event-comm-save">Enregistrer</Button></div>}
      <Section title="Collectes photo & vidéo" testid="event-comm-requests"><Requests eventId={eid} write={w} sending={sending} /></Section>
    </div>);
}
