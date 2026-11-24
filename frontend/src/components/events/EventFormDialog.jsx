import { useEffect, useState } from "react";
import { toast } from "sonner";
import { TitleTranslations } from "@/components/events/TitleTranslations";
import { Check } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Field } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { LanguageSelect } from "@/lib/i18n";
import { EVENT_TYPES } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { Overlaps } from "@/components/events/Overlaps";
import { PeopleFields } from "@/components/events/PeopleFields";
import { ProviderDialog } from "@/components/providers/ProviderDialog";
import { VenueField, venueDraftOk, venueComplete } from "@/components/events/VenueField";

const EMPTY = { planner_person_id: null, planner_cc_person_ids: [], title: "", type: "Mariage", client_id: "", venue_id: "", delivery_venue_id: "", delivery_same_as_venue: true, chef_projet_id: "", start: "", end: "", setup_start: "", return_end: "", guests: 0, budget: 0, budget_tax_mode: "ttc", notes: "", client_contact_ids: [], signatory_contact_id: "", planner_contact_id: "", main_contact_role: "client", planner_commission_mode: "none", planner_commission_value: 0, planner_commission_status: "due", language: "" };
const num = (s) => Number(String(s ?? "").replace(/[^\d,.-]/g, "").replace(",", ".")) || 0;
const fr = (n) => (n ? new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(n) : "");

const Pick = ({ value, onChange, items, placeholder, testid }) => (
  <Select value={value || "none"} onValueChange={(v) => onChange(v === "none" ? "" : v)}>
    <SelectTrigger data-testid={testid}><SelectValue placeholder={placeholder} /></SelectTrigger>
    <SelectContent>
      <SelectItem value="none">— Aucun —</SelectItem>
      {items.map((i) => <SelectItem key={i.id} value={i.id}>{i.label}</SelectItem>)}
    </SelectContent>
  </Select>
);

const Money = ({ value, onChange, testid, placeholder = "12 500" }) => (
  <div className="relative"><Input inputMode="decimal" className="pr-8" value={value} onChange={(e) => onChange(e.target.value)} onBlur={() => onChange(fr(num(value)))} placeholder={placeholder} data-testid={testid} />
    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">€</span></div>
);

export default function EventFormDialog({ open, onOpenChange, event, onSaved }) {
  const { can } = useMe();
  const fin = can("finance:read");
  const [f, setF] = useState(EMPTY);
  const [refs, setRefs] = useState({ contacts: [], venues: [], team: [], catalog: [], defaults: {}, planners: [], cats: [] });
  const [np, setNp] = useState(null);
  const [busy, setBusy] = useState(false);
  const [mods, setMods] = useState([]);
  const [auto, setAuto] = useState(true);
  const [modErr, setModErr] = useState(false);
  const [budget, setBudget] = useState("");
  const [mb, setMb] = useState({});
  const [split, setSplit] = useState(false);
  const [nv, setNv] = useState(null);
  const [ndv, setNdv] = useState(null);

  useEffect(() => {
    if (!open) return;
    const em = event?.modules || [];
    setF(event ? Object.fromEntries(Object.keys(EMPTY).map((k) => [k, event[k] ?? EMPTY[k]])) : EMPTY);
    setMods(em.map((m) => m.module_key));
    setMb(Object.fromEntries(em.map((m) => [m.module_key, fr(m.budget_amount)])));
    setSplit(em.some((m) => m.budget_amount > 0));
    setBudget(fr(event?.budget));
    setAuto(!event); setModErr(false); setNp(null); setNv(null); setNdv(null);
    Promise.all([can("contacts:read") ? api.get("/contacts") : { data: [] }, api.get("/venues"), api.get("/team"), api.get("/modules"), can("contacts:read") ? api.get("/organizers") : { data: [] }, can("providers:manage") ? api.get("/provider-categories") : { data: [] }]).then(([c, v, t, m, wp, pcats]) => {
      const extra = em.filter((x) => !m.data.modules.some((y) => y.key === x.module_key)).map((x) => ({ key: x.module_key, label: x.label }));
      setRefs({ contacts: c.data.map((x) => ({ id: x.id, label: x.display_name, sub: [x.company, x.city].filter(Boolean).join(" · "), client: (x.types || []).includes("client") })), planners: wp.data, cats: pcats.data, venues: v.data, team: t.data.map((x) => ({ id: x.id, label: x.name })), catalog: [...m.data.modules, ...extra], defaults: m.data.defaults });
      if (!event) setMods(m.data.defaults[EMPTY.type] || []);
    });
  }, [open, event, can]);

  const set = (k) => (e) => setF({ ...f, [k]: e?.target ? e.target.value : e });
  const setType = (type) => { setF({ ...f, type }); if (auto) setMods(refs.defaults[type] || []); };
  const toggle = (k) => { setAuto(false); const next = mods.includes(k) ? mods.filter((x) => x !== k) : [...mods, k]; setMods(next); setModErr(!event && !next.length); };
  const same = f.delivery_same_as_venue;
  const rental = mods.includes("loueur_materiel");
  const total = mods.reduce((n, k) => n + num(mb[k]), 0);
  const gap = num(budget) - total;

  const [inv, setInv] = useState(true);
  const submit = async (e) => {
    e.preventDefault();
    if (!event && !mods.length) { setModErr(true); return toast.error("Sélectionnez au moins un module"); }
    if ((nv && !venueDraftOk(nv)) || (!same && ndv && !venueDraftOk(ndv))) return toast.error("Complétez les champs obligatoires du nouveau lieu");
    const find = (id) => refs.venues.find((v) => v.id === id);
    if (rental && !venueComplete(same ? nv || find(f.venue_id) : ndv || find(f.delivery_venue_id))) return toast.error("Location de matériel : un lieu de livraison complet (adresse, code postal, ville) est obligatoire");
    setBusy(true);
    const body = { ...f, client_id: f.signatory_contact_id, planner_commission_value: num(f.planner_commission_value), guests: Number(f.guests) || 0, budget: num(budget), venue_id: nv ? "" : f.venue_id, delivery_venue_id: same || ndv ? "" : f.delivery_venue_id };
    if (nv) body.new_venue = nv;
    if (!same && ndv) body.new_delivery_venue = ndv;
    if (mods.length || !event) { body.modules = mods; body.module_budgets = Object.fromEntries(mods.map((k) => [k, split ? num(mb[k]) : 0])); }
    if (!fin) { delete body.budget; delete body.budget_tax_mode; delete body.module_budgets; }
    try {
      const r = event ? await api.patch(`/events/${event.id}`, body) : await api.post("/events", body);
      toast.success(event ? "Événement mis à jour" : `Événement ${r.data.code} créé`);
      if (!event && inv && (body.client_contact_ids?.length || body.client_id)) api.post(`/events/${r.data.id}/portal/invite`, { contact_ids: [] }).then((x) => x.data.some((i) => i.sent) && toast.success("Invitation à l'espace client envoyée")).catch(() => {});
      (r.data.dj_conflicts || []).forEach((c) => toast.error(`Conflit DJ : ${c}`, { duration: 12000 }));
      onSaved?.(r.data);
      onOpenChange(false);
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" onEscapeKeyDown={(e) => { if (document.activeElement?.getAttribute("aria-expanded") === "true") e.preventDefault(); }}>
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{event ? "Modifier l'événement" : "Nouvel événement"}</DialogTitle></DialogHeader>
        <ProviderDialog inline organizerTypes={refs.cats.filter((c) => c.is_organizer)} open={np !== null} onOpenChange={() => setNp(null)} provider={null} categories={refs.cats} onOpenExisting={() => toast.info("Ce prestataire existe déjà : sélectionnez-le dans la liste des organisateurs")}
          preset={{ first_name: (np || "").split(" ")[0], last_name: (np || "").split(" ").slice(1).join(" "), categories: ["wedding_planner"] }}
          onSaved={(p) => { setRefs((r) => ({ ...r, planners: [...r.planners, { contact_id: p.contact_id, provider_id: p.id, display_name: p.display_name, company: p.company, city: p.base_city }] })); setF((cur) => ({ ...cur, planner_contact_id: p.contact_id, main_contact_role: "planner" })); setNp(null); }} />
        <form onSubmit={submit} className={np !== null ? "hidden" : "grid grid-cols-1 gap-4 sm:grid-cols-2"} data-testid="event-form">
          <Field label="Intitulé" className="sm:col-span-2"><Input data-testid="event-title-input" value={f.title} onChange={set("title")} required placeholder="Mariage Camille & Thomas" />{event?.id && <TitleTranslations base={`/events/${event.id}`} label="Traductions" />}</Field>
          <Field label="Type">
            <Select value={f.type} onValueChange={setType}><SelectTrigger data-testid="event-type-select"><SelectValue /></SelectTrigger>
              <SelectContent>{EVENT_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent></Select>
          </Field>
          <Field label="Invités"><Input type="number" min="0" data-testid="event-guests-input" value={f.guests} onChange={set("guests")} /></Field>
          {can("contacts:read") && <PeopleFields f={f} setF={setF} contacts={refs.contacts} planners={refs.planners} fin={fin} canCreate={can("providers:manage")} onCreatePlanner={setNp} />}
          <Field label="Langue des documents (devis, factures, bon de livraison)"><LanguageSelect auto="Langue du client signataire" value={f.language} onChange={set("language")} testid="event-language-select" /></Field>
          <Field label="Chef de projet"><Pick testid="event-chef-select" value={f.chef_projet_id} onChange={set("chef_projet_id")} items={refs.team} /></Field>

          <VenueField label="Lieu de l'événement" testid="event-venue" venues={refs.venues} value={f.venue_id} onChange={set("venue_id")} draft={nv} onDraft={setNv} />
          {(f.venue_id || nv) && (
            <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={same} onChange={(e) => setF({ ...f, delivery_same_as_venue: e.target.checked })} data-testid="event-delivery-same" />Adresse de livraison identique au lieu de réception</label>
          )}
          {(f.venue_id || nv) && !same && <VenueField label={`Lieu de livraison${rental ? " *" : ""}`} testid="event-delivery-venue" venues={refs.venues} value={f.delivery_venue_id} onChange={set("delivery_venue_id")} draft={ndv} onDraft={setNdv} />}

          <div className="sm:col-span-2" data-testid="event-modules">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Modules à activer{event ? "" : " *"}</div>
            <div className="flex flex-wrap gap-2">
              {refs.catalog.map((m) => {
                const on = mods.includes(m.key);
                return <button key={m.key} type="button" aria-pressed={on} onClick={() => toggle(m.key)} data-testid={`event-module-${m.key}`}
                  className={`inline-flex h-9 items-center gap-1.5 rounded-full border px-4 text-sm font-medium transition-colors ${on ? "border-primary bg-primary text-white" : "border-border hover:border-foreground/40"}`}>{on && <Check className="h-4 w-4" />}{m.label}</button>;
              })}
            </div>
            {modErr && <div className="mt-1 text-xs text-red-600 dark:text-red-400" data-testid="event-modules-error">Sélectionnez au moins un module.</div>}
            {rental && <div className="mt-1 text-xs text-muted-foreground">Location de matériel : le lieu de livraison complet est obligatoire.</div>}
          </div>

          {fin && (
            <div className="sm:col-span-2" data-testid="event-budget">
              <div className="flex flex-wrap items-end gap-3">
                <Field label="Budget global (€)" className="min-w-40 flex-1"><Money value={budget} onChange={setBudget} testid="event-budget-input" /></Field>
                <div className="flex rounded-full border border-border p-1">{["ht", "ttc"].map((m) => <button key={m} type="button" onClick={() => setF({ ...f, budget_tax_mode: m })} data-testid={`event-budget-${m}`} className={`rounded-full px-4 py-1.5 text-xs font-semibold uppercase ${f.budget_tax_mode === m ? "bg-foreground text-background" : "text-muted-foreground"}`}>{m}</button>)}</div>
                {mods.length > 0 && <button type="button" className="pb-2 text-sm font-semibold underline" onClick={() => setSplit(!split)} data-testid="event-budget-split-toggle">{split ? "Masquer la répartition" : "Répartir par module"}</button>}
              </div>
              {split && mods.length > 0 && (
                <div className="mt-3 grid grid-cols-1 gap-3 rounded-2xl border border-border p-4 sm:grid-cols-2" data-testid="event-budget-split">
                  {mods.map((k) => <Field key={k} label={refs.catalog.find((m) => m.key === k)?.label || k}><Money value={mb[k] || ""} onChange={(v) => setMb({ ...mb, [k]: v })} placeholder="0" testid={`event-module-budget-${k}`} /></Field>)}
                  <div className="text-sm sm:col-span-2" data-testid="event-budget-total">Total réparti : <b>{fr(total) || 0} €</b>{num(budget) > 0 && <> · Écart avec le budget global : <b>{gap === 0 ? "0" : fr(gap)} €</b></>}</div>
                  {num(budget) > 0 && gap < 0 && <div className="rounded-xl bg-amber-500/10 p-3 text-sm font-medium text-amber-600 dark:text-amber-400 sm:col-span-2" data-testid="event-budget-over">La répartition dépasse le budget global de {fr(-gap)} €.</div>}
                </div>
              )}
            </div>
          )}

          <Field label="Début de la prestation"><Input type="datetime-local" data-testid="event-start-input" value={f.start} onChange={set("start")} required /></Field>
          <Field label="Fin de la prestation"><Input type="datetime-local" data-testid="event-end-input" value={f.end} onChange={set("end")} required /></Field>
          <Field label="Sortie dépôt / montage"><Input type="datetime-local" data-testid="event-setup-input" value={f.setup_start} onChange={set("setup_start")} /></Field>
          <Field label="Retour dépôt"><Input type="datetime-local" data-testid="event-return-input" value={f.return_end} onChange={set("return_end")} /></Field>
          <p className="text-xs text-muted-foreground sm:col-span-2">La période de réservation du matériel va de la sortie dépôt au retour (montage et démontage inclus). Laissés vides, ils reprennent le début et la fin.</p>
          <Overlaps start={f.setup_start || f.start} end={f.return_end || f.end} venueId={f.venue_id} exclude={event?.id} />
          <Field label="Notes" className="sm:col-span-2"><Textarea data-testid="event-notes-input" value={f.notes} onChange={set("notes")} rows={3} /></Field>
          {!event && <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" checked={inv} onChange={(e) => setInv(e.target.checked)} data-testid="event-invite-client" />Inviter le client dans son espace</label>}
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Annuler</Button>
            <Button data-testid="event-form-submit" disabled={busy}>{event ? "Enregistrer" : "Créer l'événement"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
