import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));
const Radio = ({ name, value, cur, set, label }) => <label className="flex items-center gap-2"><input type="radio" name={name} checked={cur === value} onChange={() => set(value)} data-testid={`dup-${name}-${value}`} />{label}</label>;

function DuplicateDialog({ q, onClose, onDone }) {
  const [f, setF] = useState({ destination: "same", client: "source", dates: "source", prices: "source" });
  const [evs, setEvs] = useState([]);
  const [evText, setEvText] = useState("");
  const [op, setOp] = useState({ start: "", end: "" });
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get("/events").then((r) => setEvs(r.data)).catch(() => {}); }, []);
  const dest = (destination) => setF({ ...f, destination, client: destination === "event" ? "event" : "source", dates: destination === "event" ? "event" : f.dates === "event" ? "source" : f.dates });
  const ev = evs.find((x) => `${x.code} · ${x.title}` === evText);
  const other = f.destination === "event";
  const submit = async () => {
    if (other && !ev) return toast.error("Choisissez l'événement de destination dans la liste");
    if (f.dates === "custom" && !(op.start && op.end)) return toast.error("Saisissez le début et la fin de l'exploitation");
    setBusy(true);
    const slot = { enabled: true, date: "", start: "", end: "" };
    try {
      const { data } = await api.post(`/quotes/${q.id}/duplicate`, { ...f, event_id: other ? ev.id : "", custom_dates: f.dates === "custom" ? { delivery: slot, pickup: slot, operation: op, delivery_same_day: true, pickup_after_operation: true } : null });
      data.warnings.forEach((w) => toast.warning(w, { duration: 10000 }));
      toast.success(`Devis ${data.number} créé en brouillon (dupliqué de ${q.number})`);
      onDone?.(data); onClose();
    } catch (e) { ko(e); }
    setBusy(false);
  };
  const tpl = async () => { const name = window.prompt("Nom du modèle de devis", q.event_title || q.number); if (!name) return; try { await api.post("/quote-templates", { quote_id: q.id, name }); toast.success("Modèle de devis enregistré"); } catch (e) { ko(e); } };
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[92vh] max-w-xl overflow-y-auto" data-testid="duplicate-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">Dupliquer le devis {q.number}</DialogTitle></DialogHeader>
        <p className="text-xs text-muted-foreground">Crée un devis indépendant en brouillon, avec un nouveau numéro. Le devis d'origine n'est pas modifié.</p>
        <div className="space-y-4 text-sm">
          <div className="space-y-1"><div className="font-semibold">Destination</div>
            {q.event_id && <Radio name="destination" value="same" cur={f.destination} set={dest} label="Même événement" />}
            <Radio name="destination" value="event" cur={f.destination} set={dest} label="Un autre événement" />
            {other && <><Input list="dup-events" value={evText} onChange={(e) => setEvText(e.target.value)} placeholder="Code ou titre de l'événement" data-testid="dup-event-input" /><datalist id="dup-events">{evs.filter((x) => x.id !== q.event_id).map((x) => <option key={x.id} value={`${x.code} · ${x.title}`} />)}</datalist></>}
            <Radio name="destination" value="none" cur={f.destination} set={dest} label="Sans événement" /></div>
          <div className="space-y-1"><div className="font-semibold">Client</div>
            <Radio name="client" value="source" cur={f.client} set={(client) => setF({ ...f, client })} label="Garder celui du devis" />
            {other && <Radio name="client" value="event" cur={f.client} set={(client) => setF({ ...f, client })} label="Reprendre celui de l'événement de destination" />}</div>
          <div className="space-y-1"><div className="font-semibold">Dates</div>
            <Radio name="dates" value="source" cur={f.dates} set={(dates) => setF({ ...f, dates })} label="Garder celles du devis" />
            {other && <Radio name="dates" value="event" cur={f.dates} set={(dates) => setF({ ...f, dates })} label="Reprendre celles de l'événement de destination" />}
            <Radio name="dates" value="custom" cur={f.dates} set={(dates) => setF({ ...f, dates })} label="Les saisir" />
            {f.dates === "custom" && <div className="flex flex-wrap items-center gap-2"><Input type="datetime-local" className="w-56" value={op.start} onChange={(e) => setOp({ ...op, start: e.target.value })} data-testid="dup-op-start" /><span>→</span><Input type="datetime-local" className="w-56" value={op.end} onChange={(e) => setOp({ ...op, end: e.target.value })} data-testid="dup-op-end" /><span className="text-xs text-muted-foreground">Livraison et retrait ajustables ensuite dans le devis.</span></div>}</div>
          <div className="space-y-1"><div className="font-semibold">Prix</div>
            <Radio name="prices" value="source" cur={f.prices} set={(prices) => setF({ ...f, prices })} label="Garder les prix du devis" />
            <Radio name="prices" value="catalog" cur={f.prices} set={(prices) => setF({ ...f, prices })} label="Recalculer aux tarifs actuels du catalogue (remises conservées)" /></div>
        </div>
        <DialogFooter className="gap-2"><Button type="button" variant="outline" onClick={tpl} data-testid="dup-save-template">Enregistrer comme modèle de devis</Button><Button type="button" disabled={busy} onClick={submit} data-testid="dup-submit"><Copy />Dupliquer</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DuplicateButton({ q, onDone, variant = "outline", label = "Dupliquer" }) {
  const [open, setOpen] = useState(false);
  return (<><Button type="button" size="sm" variant={variant} onClick={() => setOpen(true)} data-testid={`quote-duplicate-${q.number}`}><Copy />{label}</Button>{open && <DuplicateDialog q={q} onClose={() => setOpen(false)} onDone={onDone} />}</>);
}
