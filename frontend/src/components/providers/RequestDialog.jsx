import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Field } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { EVENT_TYPES, toLocalInput } from "@/lib/constants";
import { Chips, EQUIP, GeoInput } from "@/components/providers/shared";

const empty = () => ({ event_id: "", category_key: "", quantity: 1, date: "", start_time: "18:00", end_time: "20:00", venue_name: "", venue_address: "", venue_zip: "", venue_city: "", venue_lat: null,
  venue_lng: null, onsite_contact: "", access_instructions: "", event_type: "", guest_count: 0, brief: "", onsite_equipment: [], onsite_equipment_note: "", budget_min: 0, budget_max: 0,
  budget_tax_mode: "HT", hide_budget: false, reply_deadline: toLocalInput(new Date(Date.now() + 48 * 3600000)) });

export function RequestDialog({ open, onOpenChange, categories, eventId, request, onSaved }) {
  const nav = useNavigate();
  const [f, setF] = useState(empty());
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    setTitle("");
    if (request) { setF({ ...empty(), ...Object.fromEntries(Object.keys(empty()).map((k) => [k, request[k] ?? empty()[k]])), event_id: request.event_id || "", reply_deadline: toLocalInput(new Date(request.reply_deadline)) }); return; }
    setF(empty());
    if (eventId) api.get("/service-requests/prefill", { params: { event_id: eventId } }).then((r) => { const { event_title, ...d } = r.data; setTitle(event_title); setF((cur) => ({ ...cur, ...d })); }).catch((e) => toast.error(errMsg(e)));
  }, [open, eventId, request]);
  const set = (k) => (e) => setF((cur) => ({ ...cur, [k]: e?.target ? e.target.value : e }));
  const [h1, m1] = f.start_time.split(":").map(Number); const [h2, m2] = f.end_time.split(":").map(Number);
  const dur = f.start_time && f.end_time ? (((h2 * 60 + m2 - h1 * 60 - m1) % 1440) + 1440) % 1440 / 60 || 24 : 0;
  const submit = async (e) => {
    e.preventDefault();
    if (!f.category_key) { toast.error("Choisissez un métier"); return; }
    setBusy(true);
    const body = { ...f, quantity: Number(f.quantity) || 1, guest_count: Number(f.guest_count) || 0, budget_min: Number(f.budget_min) || 0, budget_max: Number(f.budget_max) || 0 };
    try {
      const r = request ? await api.put(`/service-requests/${request.id}`, body) : await api.post("/service-requests", body);
      onOpenChange(false);
      if (request) onSaved?.(r.data); else nav(`/prestataires/demandes/${r.data.id}`);
    } catch (err) { toast.error(errMsg(err)); }
    setBusy(false);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="request-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{request ? "Modifier le besoin" : "Trouver un prestataire"}</DialogTitle>
          {title && <p className="text-sm text-muted-foreground" data-testid="request-event-title">Pour l'événement : {title}</p>}</DialogHeader>
        <form onSubmit={submit} className="grid grid-cols-2 gap-4">
          <Field label="Métier *"><Select value={f.category_key} onValueChange={set("category_key")}><SelectTrigger data-testid="request-category"><SelectValue placeholder="Choisir" /></SelectTrigger>
            <SelectContent>{categories.filter((c) => c.active).map((c) => <SelectItem key={c.key} value={c.key} data-testid={`request-category-${c.key}`}>{c.label}</SelectItem>)}</SelectContent></Select></Field>
          <Field label="Nombre nécessaire"><Input type="number" min={1} value={f.quantity} onChange={set("quantity")} data-testid="request-quantity" /></Field>
          <Field label="Date *"><Input type="date" required value={f.date} onChange={set("date")} data-testid="request-date" /></Field>
          <div className="grid grid-cols-2 gap-2"><Field label="Début *"><Input type="time" required value={f.start_time} onChange={set("start_time")} data-testid="request-start" /></Field>
            <Field label={`Fin * (${String(Math.round(dur * 100) / 100).replace(".", ",")} h)`}><Input type="time" required value={f.end_time} onChange={set("end_time")} data-testid="request-end" /></Field></div>
          <Field label="Lieu * (adresse)" className="col-span-2"><GeoInput required value={f.venue_address} testid="request-address" placeholder="Adresse ou ville"
            onText={(v) => setF({ ...f, venue_address: v, venue_lat: null, venue_lng: null })} onPick={(p, c) => setF({ ...f, venue_address: p.name, venue_zip: p.postcode || "", venue_city: p.city || "", venue_lat: c?.[1] ?? null, venue_lng: c?.[0] ?? null })} /></Field>
          <Field label="Code postal"><Input value={f.venue_zip} onChange={set("venue_zip")} data-testid="request-zip" /></Field>
          <Field label="Ville"><Input value={f.venue_city} onChange={set("venue_city")} data-testid="request-city" /></Field>
          <Field label="Type d'événement"><Select value={f.event_type} onValueChange={set("event_type")}><SelectTrigger data-testid="request-event-type"><SelectValue placeholder="Choisir" /></SelectTrigger><SelectContent>{EVENT_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent></Select></Field>
          <Field label="Invités"><Input type="number" min={0} value={f.guest_count} onChange={set("guest_count")} data-testid="request-guests" /></Field>
          <Field label="Brief (mission, tenue, contraintes)" className="col-span-2"><Textarea rows={3} value={f.brief} onChange={set("brief")} data-testid="request-brief" /></Field>
          <Field label="Matériel disponible sur place" className="col-span-2"><Chips options={Object.entries(EQUIP)} value={f.onsite_equipment} onChange={set("onsite_equipment")} testid="request-equipment" /></Field>
          <Field label="Autre matériel sur place" className="col-span-2"><Input value={f.onsite_equipment_note} onChange={set("onsite_equipment_note")} /></Field>
          <Field label="Budget minimum (€)"><Input type="number" min={0} value={f.budget_min} onChange={set("budget_min")} data-testid="request-budget-min" /></Field>
          <Field label="Budget maximum ou fixe (€)"><Input type="number" min={0} value={f.budget_max} onChange={set("budget_max")} data-testid="request-budget-max" /></Field>
          <Field label="Budget exprimé en"><Select value={f.budget_tax_mode} onValueChange={set("budget_tax_mode")}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="HT">HT</SelectItem><SelectItem value="TTC">TTC</SelectItem></SelectContent></Select></Field>
          <label className="flex items-center gap-3 self-end pb-2 text-sm"><Switch checked={f.hide_budget} onCheckedChange={set("hide_budget")} data-testid="request-hide-budget" />Masquer le budget au prestataire</label>
          <Field label="Date limite de réponse"><Input type="datetime-local" required value={f.reply_deadline} onChange={set("reply_deadline")} data-testid="request-deadline" /></Field>
          <Field label="Contact sur place (pour la confirmation)"><Input value={f.onsite_contact} onChange={set("onsite_contact")} /></Field>
          <Field label="Accès (pour la confirmation)" className="col-span-2"><Input value={f.access_instructions} onChange={set("access_instructions")} /></Field>
          <DialogFooter className="col-span-2"><Button type="submit" disabled={busy} data-testid="request-save-button">{request ? "Enregistrer" : "Chercher les prestataires"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
