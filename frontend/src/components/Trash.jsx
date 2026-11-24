import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Section, Loading } from "@/components/common";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e), { duration: 10000 });
const sel = "h-9 w-full rounded-lg border border-border bg-background px-2 text-sm";

let rightsP;
export function useTrashRights() {
  const [r, setR] = useState({});
  useEffect(() => { (rightsP = rightsP || api.get("/trash/rights")).then((x) => setR(x.data)).catch(() => {}); }, []);
  return r;
}

/** Confirmation unique de suppression : items = [{ kind, id, name }] */
export function TrashDialog({ items, onClose, onDone }) {
  const [info, setInfo] = useState(null);
  const [opt, setOpt] = useState({});
  useEffect(() => { Promise.all(items.map((i) => api.get("/trash/impact", { params: { kind: i.kind, id: i.id } }).then((r) => r.data))).then(setInfo).catch((e) => { ko(e); onClose(); }); }, [items, onClose]);
  if (!info) return null;
  const blocked = info.find((i) => i.blocked);
  const needs = Object.assign({}, ...info.map((i) => i.needs));
  const missing = (needs.new_default && !opt.new_default_id) || (needs.stock && !opt.transfer_to);
  const go = () => api.post("/trash/delete", { items: items.map(({ kind, id }) => ({ kind, id })), options: opt }).then((r) => {
    toast.success(`${r.data.deleted} élément(s) placé(s) dans la Corbeille (30 jours)`);
    r.data.alerts.forEach((a) => toast.warning(a, { duration: 12000 }));
    r.data.errors.forEach((a) => toast.error(a, { duration: 12000 }));
    onDone(); onClose();
  }).catch(ko);
  return (
    <Dialog open onOpenChange={onClose}><DialogContent data-testid="trash-dialog">
      <DialogHeader><DialogTitle>Supprimer {items.length === 1 ? info[0].label : `${items.length} éléments`}</DialogTitle><DialogDescription>L'élément part dans la Corbeille pendant 30 jours : il disparaît des listes et peut être restauré.</DialogDescription></DialogHeader>
      <ul className="max-h-60 list-disc space-y-1 overflow-y-auto pl-5 text-sm" data-testid="trash-impact">{info.flatMap((i) => i.lines.map((l, k) => <li key={i.id + k}>{items.length > 1 ? `${i.label} : ` : ""}{l}</li>))}{info.every((i) => !i.lines.length) && <li className="list-none text-muted-foreground">Rien n'est rattaché à cet élément.</li>}</ul>
      {blocked && <div className="rounded-xl bg-red-500/10 p-3 text-sm text-red-700" data-testid="trash-blocked">{blocked.blocked}{blocked.credit && <> — <button className="font-semibold underline" onClick={() => api.post(`/invoices/${blocked.id}/credit-note`).then((r) => { toast.success(`Avoir ${r.data.number} créé : facture annulée`); onDone(); onClose(); }).catch(ko)} data-testid="trash-create-credit">Créer l'avoir</button></>}</div>}
      {needs.handover && <label className="text-xs text-muted-foreground">Transférer ses tâches, événements et opportunités à<select className={sel} value={opt.to_user_id || ""} onChange={(e) => setOpt({ ...opt, to_user_id: e.target.value })} data-testid="trash-handover"><option value="">— Ne rien transférer —</option>{needs.handover.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>}
      {needs.stock && <label className="text-xs text-muted-foreground">Stock de l'entrepôt<select className={sel} value={opt.transfer_to || ""} onChange={(e) => setOpt({ ...opt, transfer_to: e.target.value })} data-testid="trash-stock"><option value="">— Choisir —</option>{needs.stock.map((w) => <option key={w.id} value={w.id}>Transférer vers {w.name}</option>)}<option value="drop">Supprimer le stock avec l'entrepôt</option></select></label>}
      {needs.new_default && <label className="text-xs text-muted-foreground">Nouvel entrepôt principal<select className={sel} value={opt.new_default_id || ""} onChange={(e) => setOpt({ ...opt, new_default_id: e.target.value })} data-testid="trash-new-default"><option value="">— Choisir —</option>{needs.new_default.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></label>}
      <DialogFooter><Button variant="outline" onClick={onClose}>Annuler</Button><Button variant="destructive" disabled={!!blocked || missing} onClick={go} data-testid="trash-confirm">Supprimer</Button></DialogFooter>
    </DialogContent></Dialog>);
}

export function TrashBin() {
  const [d, setD] = useState(null);
  const [pick, setPick] = useState([]);
  const load = useCallback(() => api.get("/trash").then((r) => { setD(r.data); setPick([]); }).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return <Loading />;
  const key = (r) => `${r.kind}:${r.id}`;
  const items = d.rows.filter((r) => pick.includes(key(r))).map(({ kind, id }) => ({ kind, id }));
  const call = (path, body, msg, confirm) => (!confirm || window.confirm(confirm)) && api.post(path, body).then(() => { toast.success(msg); load(); }).catch(ko);
  return (
    <Section title="Corbeille" actions={<div className="flex gap-2">
      <Button size="sm" variant="outline" disabled={!items.length} onClick={() => call("/trash/restore", { items }, "Restauré")} data-testid="trash-restore-selection">Restaurer la sélection</Button>
      <Button size="sm" variant="outline" disabled={!items.length} onClick={() => call("/trash/purge", { items }, "Supprimé définitivement", `Supprimer définitivement ${items.length} élément(s) ? Cette action est irréversible.`)} data-testid="trash-purge-selection">Supprimer définitivement</Button>
      <Button size="sm" variant="destructive" disabled={!d.rows.length} onClick={() => call("/trash/empty", {}, "Corbeille vidée", "Vider la corbeille ? Tous les éléments et leurs fichiers sont effacés définitivement.")} data-testid="trash-empty">Vider la corbeille</Button></div>}>
      <p className="mb-3 text-sm text-muted-foreground">Les éléments supprimés restent ici {d.days} jours, puis sont effacés automatiquement avec leurs fichiers.</p>
      <div className="divide-y divide-border" data-testid="trash-list">{d.rows.length === 0 && <p className="py-3 text-sm text-muted-foreground">La corbeille est vide.</p>}{d.rows.map((r) => (
        <div key={key(r)} className="flex flex-wrap items-center gap-3 py-2 text-sm" data-testid={`trash-row-${r.id}`}>
          <input type="checkbox" checked={pick.includes(key(r))} onChange={(e) => setPick(e.target.checked ? [...pick, key(r)] : pick.filter((x) => x !== key(r)))} data-testid={`trash-pick-${r.id}`} />
          <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-semibold">{r.type}</span><span className="font-semibold">{r.label}</span>
          <span className="text-xs text-muted-foreground">supprimé le {r.deleted_at.slice(0, 10)}{r.deleted_by ? ` par ${r.deleted_by}` : ""}{r.purge_at ? ` · purge le ${r.purge_at.slice(0, 10)}` : ""}</span><span className="ml-auto" />
          <Button size="sm" variant="ghost" onClick={() => call("/trash/restore", { items: [{ kind: r.kind, id: r.id }] }, "Restauré")} data-testid={`trash-restore-${r.id}`}>Restaurer</Button>
        </div>))}</div>
    </Section>);
}

/** Barre de sélection multiple réutilisable dans les listes */
export function BulkDelete({ kind, picked, names, onDone }) {
  const [open, setOpen] = useState(false);
  if (!picked.length) return null;
  return <><Button size="sm" variant="destructive" onClick={() => setOpen(true)} data-testid={`bulk-delete-${kind}`}>Supprimer la sélection ({picked.length})</Button>{open && <TrashDialog items={picked.map((id) => ({ kind, id, name: names?.[id] }))} onClose={() => setOpen(false)} onDone={onDone} />}</>;
}

/** Bouton « Supprimer » d'une ligne ou d'une fiche : masqué sans le droit Supprimer du module */
export function TrashBtn({ kind, id, name, onDone, className = "" }) {
  const r = useTrashRights();
  const [open, setOpen] = useState(false);
  if (!r[kind]) return null;
  return (<span onClick={(e) => e.stopPropagation()}>
    <span role="button" tabIndex={0} aria-label="Supprimer" title="Supprimer" className={`icon-btn inline-flex cursor-pointer text-red-600 ${className}`} onClick={() => setOpen(true)} onKeyDown={(e) => e.key === "Enter" && setOpen(true)} data-testid={`trash-btn-${kind}-${id}`}><Trash2 className="h-4 w-4" /></span>
    {open && <TrashDialog items={[{ kind, id, name }]} onClose={() => setOpen(false)} onDone={onDone} />}</span>);
}

export const Pick = ({ id, pick, setPick }) => <input type="checkbox" className="mr-2" aria-label="Sélectionner" onClick={(e) => e.stopPropagation()} checked={pick.includes(id)} onChange={(e) => setPick(e.target.checked ? [...pick, id] : pick.filter((x) => x !== id))} data-testid={`pick-${id}`} />;
