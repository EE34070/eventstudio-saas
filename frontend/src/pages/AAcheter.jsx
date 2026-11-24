import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, Loading, EmptyState } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtDate } from "@/lib/constants";
import { Offers } from "@/components/catalogue/Suppliers";
import { useMe } from "@/context/MeContext";

const ko = (e) => toast.error(errMsg(e));
const ST = { a_acheter: "À acheter", commande: "Commandé", recu: "Reçu" };
const BLANK = { label: "", qty: 1, needed_by: "", note: "" };

export default function AAcheter() {
  const { can } = useMe();
  const write = can("finance:write");
  const [rows, setRows] = useState(null);
  const [f, setF] = useState(BLANK);
  const load = useCallback(() => api.get("/purchase-needs").then((r) => setRows(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!rows) return <Loading />;
  const add = () => api.post("/purchase-needs", { ...f, qty: Number(f.qty) || 1 }).then(() => { setF(BLANK); toast.success("Ligne ajoutée"); load(); }).catch(ko);
  return (
    <div data-testid="purchase-needs-page">
      <PageHeader eyebrow="Achats" title="À acheter" subtitle="Articles à acheter, dont ceux créés depuis un manque de matériel sur un événement. « Reçu » ne modifie pas le stock : saisissez l'entrée dans Entrepôts & stocks." />
      {write && <div className="card-soft mb-4 flex flex-wrap items-end gap-2 p-4">
        <Input className="w-64" placeholder="Article *" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} data-testid="need-label" />
        <Input className="w-24" type="number" min="1" title="Quantité" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} data-testid="need-qty" />
        <Input className="w-44" type="date" title="Date nécessaire" value={f.needed_by} onChange={(e) => setF({ ...f, needed_by: e.target.value })} data-testid="need-date" />
        <Input className="w-64" placeholder="Note" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        <Button disabled={!f.label.trim()} onClick={add} data-testid="need-add"><Plus />Ajouter</Button></div>}
      {!rows.length ? <EmptyState title="Rien à acheter" text="Choisissez « Achat » sur un manque de matériel pour créer une ligne liée à l'événement." /> : (
        <div className="card-soft overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="px-3 py-2">Article</th><th className="px-3 py-2">Quantité</th><th className="px-3 py-2">Date nécessaire</th><th className="px-3 py-2">Événement</th><th className="px-3 py-2">Note</th><th className="px-3 py-2">Statut</th><th /></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id} className="border-b border-border last:border-0" data-testid={`need-row-${r.id}`}>
            <td className="px-3 py-2 font-medium">{r.label}<Offers offers={r.offers} testid={`need-offers-${r.id}`} /></td><td className="px-3 py-2">{r.qty}</td><td className="px-3 py-2">{r.needed_by ? fmtDate(r.needed_by) : "—"}</td>
            <td className="px-3 py-2">{r.event_id ? <Link className="underline" to={`/evenements/${r.event_id}?tab=materiel`} data-testid={`need-event-${r.id}`}>{r.event_code} · {r.event_title}</Link> : "—"}</td>
            <td className="px-3 py-2 text-xs text-muted-foreground">{r.note}</td>
            <td className="px-3 py-2"><select className="h-9 rounded-lg border border-border bg-background px-2 text-xs" disabled={!write} value={r.status} onChange={(e) => api.patch(`/purchase-needs/${r.id}`, { status: e.target.value }).then(load).catch(ko)} data-testid={`need-status-${r.id}`}>{Object.entries(ST).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
            <td className="px-3 py-2">{write && <button aria-label="Supprimer" onClick={() => window.confirm("Supprimer cette ligne ?") && api.delete(`/purchase-needs/${r.id}`).then(load).catch(ko)} data-testid={`need-delete-${r.id}`}><Trash2 className="h-4 w-4" /></button>}</td></tr>)}</tbody></table></div>)}
    </div>
  );
}
