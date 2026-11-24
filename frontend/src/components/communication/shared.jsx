import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy, Plus, Send, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";

export const ko = (e) => toast.error(errMsg(e));
export const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
export const RIGHTS = { ok: "Droits accordés", to_confirm: "Droits à confirmer", refused: "Droits refusés" };
export const REQ = { a_envoyer: "À envoyer", demandee: "Demandée", recue: "Reçue", close: "Clôturée" };
export const REM = { planifiee: "planifiée", envoyee: "envoyée", retenue: "non envoyée (hors production)", sautee: "regroupée" };
export const copy = (t, msg = "Copié") => navigator.clipboard.writeText(t).then(() => toast.success(msg)).catch(() => toast.error("Copie impossible"));

export async function chunked(http, base, file, body, onProgress) {
  const { data: u } = await http.post(base, { filename: file.name, size: file.size });
  for (let i = 0; i < u.chunks; i += 1) {
    await http.put(`${base}/${u.id}/chunks/${i}`, file.slice(i * u.chunk_size, (i + 1) * u.chunk_size), { headers: { "Content-Type": "application/octet-stream" } });
    if (onProgress) onProgress(Math.round(((i + 1) / u.chunks) * 100));
  }
  return (await http.post(`${base}/${u.id}/complete`, body)).data;
}

export function Requests({ eventId, events, write, sending }) {
  const [rows, setRows] = useState([]);
  const [f, setF] = useState({ event_id: eventId || "", name: "", email: "", due_date: "" });
  const load = useCallback(() => api.get("/communication/requests", { params: { event_id: eventId || "" } }).then((r) => setRows(r.data)).catch(ko), [eventId]);
  useEffect(() => { load(); }, [load]);
  const link = (r) => `${window.location.origin}/depot/${r.token}`;
  return (
    <div data-testid="comm-requests">
      {!sending && <div className="mb-3 rounded-lg bg-amber-500/10 p-2 text-xs text-amber-700" data-testid="comm-no-send">Préversion : aucune demande ni relance n'est envoyée par e-mail. Elles sont programmées et visibles ; l'envoi réel n'a lieu qu'en production.</div>}
      {write && <div className="mb-3 flex flex-wrap items-end gap-2">
        {!eventId && <select className={sel} value={f.event_id} onChange={(e) => setF({ ...f, event_id: e.target.value })} data-testid="request-event"><option value="">Événement…</option>{(events || []).map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}</select>}
        <Input className="h-9 w-48" placeholder="Photographe / vidéaste" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="request-name" />
        <Input className="h-9 w-56" type="email" placeholder="E-mail" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} data-testid="request-email" />
        <Input className="h-9 w-40" type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} data-testid="request-due" />
        <Button size="sm" disabled={!f.event_id || !f.name.trim()} onClick={() => api.post("/communication/requests", f).then(() => { setF({ ...f, name: "", email: "" }); load(); }).catch(ko)} data-testid="request-create"><Plus />Collecte</Button></div>}
      <div className="card-soft divide-y divide-border">{!rows.length && <p className="p-4 text-sm text-muted-foreground">Aucune collecte.</p>}
        {rows.map((r) => (
          <div key={r.id} className="px-4 py-3 text-sm" data-testid={`request-row-${r.id}`}>
            <div className="flex flex-wrap items-center gap-2"><div className="min-w-0 flex-1"><b>{r.name}</b> <span className="text-muted-foreground">{r.email}</span><div className="text-xs text-muted-foreground">{r.event_title} · {fmtDate(r.event_start)}{r.due_date ? ` · attendu le ${fmtDate(r.due_date)}` : ""}</div></div>
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs" data-testid={`request-status-${r.id}`}>{REQ[r.status]}</span><span className="text-xs" data-testid={`request-received-${r.id}`}>{r.received} fichier(s)</span>
              <Button size="sm" variant="outline" onClick={() => copy(link(r), "Lien de dépôt copié")} data-testid={`request-link-${r.id}`}><Copy />Lien</Button>
              {write && r.status !== "close" && <Button size="sm" variant="outline" onClick={() => api.post(`/communication/requests/${r.id}/send`).then((x) => { toast.message(x.data.message); load(); }).catch(ko)} data-testid={`request-send-${r.id}`}><Send />{r.sent_at ? "Renvoyer" : "Envoyer"}</Button>}
              {write && r.status !== "close" && <button className="text-xs underline" onClick={() => api.put(`/communication/requests/${r.id}`, { status: "close" }).then(load).catch(ko)} data-testid={`request-close-${r.id}`}>Clôturer</button>}
              {write && <button aria-label="Supprimer" onClick={() => window.confirm("Supprimer cette collecte ?") && api.delete(`/communication/requests/${r.id}`).then(load).catch(ko)} data-testid={`request-delete-${r.id}`}><Trash2 className="h-4 w-4" /></button>}</div>
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground" data-testid={`request-reminders-${r.id}`}>Relances : {r.reminders.map((x) => <span key={x.offset} className="rounded-full border border-border px-2 py-0.5">J+{x.offset} · {fmtDate(x.date)} · {REM[x.status]}</span>)}</div>
          </div>))}</div>
    </div>);
}
