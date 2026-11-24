import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));

export function RoadmapSend({ eid }) {
  const [aud, setAud] = useState(null);
  const [d, setD] = useState(null);
  const [pick, setPick] = useState([]);
  useEffect(() => { if (!aud) return; setD(null); api.get(`/events/${eid}/schedule/roadmap/draft`, { params: { audience: aud } }).then((r) => { setD(r.data); setPick(r.data.recipients.filter((p) => p.email).map((p) => p.id)); }).catch(ko); }, [aud, eid]);
  const send = () => api.post(`/events/${eid}/schedule/roadmap/send`, { audience: aud, recipient_ids: pick, subject: d.subject, body: d.body }).then((r) => { toast.success(r.data.sent ? `Feuille de route envoyée à ${r.data.recipients.join(", ")}` : `Aperçu : message journalisé pour ${r.data.recipients.join(", ")}, aucun e-mail réel envoyé`); setAud(null); }).catch(ko);
  return (<>
    <Button size="sm" onClick={() => setAud("team")} data-testid="roadmap-send-open">Envoyer…</Button>
    {aud && <Dialog open onOpenChange={(o) => !o && setAud(null)}><DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="roadmap-send-dialog">
      <DialogHeader><DialogTitle>Envoyer la feuille de route</DialogTitle><DialogDescription>Relisez et modifiez le message avant l'envoi. Rien ne part sans votre clic.</DialogDescription></DialogHeader>
      <div className="flex gap-2">{[["team", "Équipe"], ["dj", "DJ"]].map(([k, l]) => <button key={k} type="button" className={`h-8 rounded-full border px-3 text-xs font-medium ${aud === k ? "border-primary bg-primary text-white" : "border-border"}`} onClick={() => setAud(k)} data-testid={`roadmap-send-${k}`}>{l}</button>)}</div>
      {d && <div className="space-y-3 text-sm">
        <div data-testid="roadmap-send-recipients"><b>Destinataires</b>{!d.recipients.length && <p className="text-muted-foreground">{aud === "dj" ? "Aucun DJ confirmé sur cet événement." : "Aucun membre d'équipe affecté à cet événement."}</p>}
          {d.recipients.map((p) => <label key={p.id} className="flex items-center gap-2"><input type="checkbox" disabled={!p.email} checked={pick.includes(p.id)} onChange={(e) => setPick(e.target.checked ? [...pick, p.id] : pick.filter((x) => x !== p.id))} />{p.name} <span className="text-xs text-muted-foreground">{p.email || "pas d'e-mail"}</span></label>)}</div>
        <Input value={d.subject} onChange={(e) => setD({ ...d, subject: e.target.value })} data-testid="roadmap-send-subject" />
        <textarea className="w-full rounded-xl border border-border bg-background p-2 font-mono text-xs" rows={14} value={d.body} onChange={(e) => setD({ ...d, body: e.target.value })} data-testid="roadmap-send-body" />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setAud(null)}>Annuler</Button><Button disabled={!pick.length || !d.subject.trim() || !d.body.trim()} onClick={send} data-testid="roadmap-send-confirm">Envoyer à {pick.length} destinataire(s)</Button></div>
      </div>}
    </DialogContent></Dialog>}
  </>);
}
