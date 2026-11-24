import { useState } from "react";
import { toast } from "sonner";
import { Tag, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));

export function LabelPicker({ labels, onPick, disabled, testid }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative">
      <button type="button" className="icon-btn" title="Classer" disabled={disabled} onClick={() => setOpen(!open)} data-testid={`${testid}-button`}><Tag className="h-[18px] w-[18px]" /></button>
      {open && <div className="absolute right-0 z-20 mt-1 max-h-72 w-72 overflow-y-auto rounded-xl border border-border bg-card p-2 text-sm shadow-lg" data-testid={`${testid}-menu`}>
        {!labels.length && <p className="p-2 text-xs text-muted-foreground">Aucun libellé : créez-en dans les réglages de la messagerie.</p>}
        {labels.map((l) => (
          <div key={l.id} className="flex items-center gap-1 rounded-lg px-2 py-1 hover:bg-secondary">
            <button type="button" className="min-w-0 flex-1 truncate text-left" style={{ paddingLeft: (l.name.split("/").length - 1) * 12 }} onClick={() => { setOpen(false); onPick(l.gmail_id, false); }} data-testid={`${testid}-pick-${l.id}`}>{l.name.split("/").pop()}</button>
            <button type="button" className="shrink-0 text-xs underline" onClick={() => { setOpen(false); onPick(l.gmail_id, true); }} data-testid={`${testid}-pick-archive-${l.id}`}>et archiver</button>
          </div>))}
      </div>}
    </span>);
}

export function LabelManager({ status, admin, onChanged }) {
  const [name, setName] = useState("");
  const done = (msg) => () => { toast.success(msg); setName(""); onChanged(); };
  return (
    <div className="rounded-2xl border border-border p-4" data-testid="settings-labels">
      <div className="font-semibold">Libellés Gmail</div>
      <p className="mt-1 text-muted-foreground">Synchronisés avec Gmail dans les deux sens. Utilisez « / » pour un sous-libellé (ex. Clients/Mariages).</p>
      <div className="mt-2 max-h-48 overflow-y-auto">{status.labels.map((l) => (
        <div key={l.id} className="flex items-center gap-2 py-1" data-testid={`label-row-${l.id}`}><span className="min-w-0 flex-1 truncate">{l.name}</span>
          <button type="button" className="text-xs underline" onClick={() => { const n = window.prompt("Nouveau nom du libellé", l.name); if (n && n !== l.name) api.put(`/messaging/labels/${l.id}`, { name: n }).then(done("Libellé renommé")).catch(ko); }} data-testid={`label-rename-${l.id}`}>renommer</button>
          {admin && <button type="button" aria-label="Supprimer" onClick={() => window.confirm(`Supprimer le libellé « ${l.name} » ? Il sera aussi supprimé dans Gmail ; les e-mails restent.`) && api.delete(`/messaging/labels/${l.id}`).then(done("Libellé supprimé")).catch(ko)} data-testid={`label-delete-${l.id}`}><Trash2 className="h-4 w-4" /></button>}</div>))}</div>
      <div className="mt-2 flex gap-2"><Input className="h-9" placeholder="Nouveau libellé" value={name} onChange={(e) => setName(e.target.value)} data-testid="label-name-input" />
        <Button size="sm" disabled={!name.trim()} onClick={() => api.post("/messaging/labels", { name }).then(done("Libellé créé")).catch(ko)} data-testid="label-create-button">Créer</Button></div>
    </div>);
}
