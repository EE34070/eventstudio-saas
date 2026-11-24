import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Field } from "@/components/common";
import { UploadButton, openFile } from "@/lib/files";
import { api, errMsg } from "@/lib/api";
import { LanguageSelect } from "@/lib/i18n";
import { fmtEur2 } from "@/lib/constants";
import { Chips, EQUIP, GeoInput, LEGAL, ListInput, NOT_SUBJECT, P_STATUS, TRAVEL } from "@/components/providers/shared";

const EMPTY = { contact_id: "", first_name: "", last_name: "", company: "", email: "", phone: "", stage_name: "", whatsapp: false, website: "", instagram: "", video_url: "",
  categories: [], tags: [], base_city: "", base_zip: "", base_lat: null, base_lng: null, radius_km: 50, departments: [], travels_everywhere: false, base_rate: 0, included_hours: 2,
  extra_hour_rate: 0, travel_fee_mode: "included", travel_fee_amount: 0, travel_km_included: 0, meal_lodging: false, meal_lodging_fee: 0, legal_status: "micro",
  vat_mode: "not_applicable_293B", vat_rate: 20, equipment_brought: "", equipment_needed: [], equipment_needed_note: "", tech_rider: "", languages: ["Français"], rating: 0, status: "active", notes: "", language: "fr-FR" };
const NUMS = ["radius_km", "base_rate", "included_hours", "extra_hour_rate", "travel_fee_amount", "travel_km_included", "meal_lodging_fee", "vat_rate"];
const H = ({ children }) => <div className="eyebrow col-span-2 mt-3 border-t border-border pt-4">{children}</div>;
const Pick = ({ value, onChange, options, testid }) => (
  <Select value={String(value)} onValueChange={onChange}><SelectTrigger data-testid={testid}><SelectValue /></SelectTrigger>
    <SelectContent>{Object.entries(options).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent></Select>
);

export function ProviderDialog({ open, onOpenChange, provider, categories, onSaved, onOpenExisting, inline, preset, organizerTypes }) {
  const [f, setF] = useState(EMPTY);
  const [dups, setDups] = useState([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setF(provider ? { ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).filter((k) => provider[k] != null).map((k) => [k, provider[k]])) } : { ...EMPTY, ...preset }); setDups([]); } }, [open, provider]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k) => (e) => setF((cur) => ({ ...cur, [k]: e?.target ? e.target.value : e }));
  const name = f.stage_name || [f.first_name, f.last_name].filter(Boolean).join(" ") || f.company;
  useEffect(() => {
    if (!open || provider || f.contact_id || !(f.email || f.phone || name.length > 2)) { setDups([]); return undefined; }
    const t = setTimeout(() => api.get("/providers/duplicates", { params: { email: f.email, phone: f.phone, name } }).then((r) => setDups(r.data)).catch(() => {}), 400);
    return () => clearTimeout(t);
  }, [open, provider, f.contact_id, f.email, f.phone, name]);
  const submit = async (e) => {
    e?.preventDefault?.();
    if (!f.categories.length) { toast.error("Choisissez au moins un métier"); return; }
    setBusy(true);
    const body = { ...f, ...Object.fromEntries(NUMS.map((k) => [k, Number(String(f[k]).replace(",", ".")) || 0])), rating: Number(f.rating) || 0 };
    try {
      const r = provider ? await api.put(`/providers/${provider.id}`, body) : await api.post("/providers", body);
      toast.success(provider ? "Fiche enregistrée" : "Prestataire créé"); onOpenChange(false); onSaved(r.data);
    } catch (err) { toast.error(errMsg(err)); }
    setBusy(false);
  };
  const subject = f.vat_mode === "subject";
  const rate = Number(String(f.base_rate).replace(",", ".")) || 0;
  const Tag = inline ? "div" : "form";
  const form = (
        <Tag onSubmit={inline ? undefined : submit} className="grid grid-cols-2 gap-4">
          {inline && organizerTypes?.length > 0 && <Field label="Type d'organisateur" className="col-span-2">
            <select className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm" data-testid="provider-organizer-type" value={f.categories.find((k) => organizerTypes.some((c) => c.key === k)) || ""}
              onChange={(e) => setF({ ...f, categories: [e.target.value, ...f.categories.filter((k) => !organizerTypes.some((c) => c.key === k))].filter(Boolean) })}>
              {organizerTypes.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select></Field>}
          {dups.map((d) => (
            <button key={d.contact_id} type="button" className="col-span-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-left text-sm" data-testid="provider-duplicate"
              onClick={() => (d.provider_id ? (onOpenChange(false), onOpenExisting(d.provider_id)) : setF({ ...f, contact_id: d.contact_id }))}>
              {d.provider_id ? "Ce prestataire existe déjà : " : "Ce contact existe déjà : "}<b className="underline">{d.provider_id ? "ouvrir sa fiche" : "créer la fiche à partir de ce contact"}</b> ({d.display_name}{d.email ? `, ${d.email}` : ""})
            </button>
          ))}
          {f.contact_id ? <p className="col-span-2 rounded-xl bg-secondary p-3 text-sm" data-testid="provider-linked-contact">Fiche rattachée à un contact existant : ses coordonnées sont conservées. <button type="button" className="underline" onClick={() => setF({ ...f, contact_id: "" })}>Annuler</button></p> : (<>
            <Field label="Prénom"><Input value={f.first_name} onChange={set("first_name")} data-testid="provider-first-name" /></Field>
            <Field label="Nom"><Input value={f.last_name} onChange={set("last_name")} data-testid="provider-last-name" /></Field>
            <Field label="Société"><Input value={f.company} onChange={set("company")} data-testid="provider-company" /></Field>
            <Field label="E-mail"><Input type="email" value={f.email} onChange={set("email")} data-testid="provider-email" /></Field>
            <Field label="Téléphone"><Input type="tel" value={f.phone} onChange={set("phone")} data-testid="provider-phone" /></Field>
          </>)}
          <Field label="Nom de scène"><Input value={f.stage_name} onChange={set("stage_name")} data-testid="provider-stage-name" /></Field>
          <Field label="Site web"><Input value={f.website} onChange={set("website")} /></Field>
          <Field label="Instagram"><Input value={f.instagram} onChange={set("instagram")} /></Field>
          <Field label="Lien vidéo démo"><Input value={f.video_url} onChange={set("video_url")} /></Field>
          <label className="flex items-center gap-3 self-end pb-2 text-sm"><Switch checked={f.whatsapp} onCheckedChange={set("whatsapp")} data-testid="provider-whatsapp" />Joignable sur WhatsApp</label>
          <Field label="Métiers *" className="col-span-2"><Chips options={categories.filter((c) => c.active || f.categories.includes(c.key)).map((c) => [c.key, c.label])} value={f.categories} onChange={set("categories")} testid="provider-categories" /></Field>
          <Field label="Sous-spécialités / tags (séparés par des virgules)" className="col-span-2"><ListInput value={f.tags} onChange={set("tags")} placeholder="sax + DJ set, jazz, deep house" data-testid="provider-tags" /></Field>

          <H>Zone d'intervention</H>
          <Field label="Ville de base"><GeoInput municipality value={f.base_city} testid="provider-base-city" placeholder="Nîmes"
            onText={(v) => setF({ ...f, base_city: v, base_lat: null, base_lng: null })} onPick={(p, c) => setF({ ...f, base_city: p.city || p.name, base_zip: p.postcode || "", base_lat: c?.[1] ?? null, base_lng: c?.[0] ?? null })} /></Field>
          <Field label="Rayon (km)"><Input type="number" min={0} value={f.radius_km} onChange={set("radius_km")} data-testid="provider-radius" /></Field>
          <Field label="Départements couverts (ex. 30, 34, 13, 84)"><ListInput value={f.departments} onChange={set("departments")} data-testid="provider-departments" /></Field>
          <label className="flex items-center gap-3 self-end pb-2 text-sm"><Switch checked={f.travels_everywhere} onCheckedChange={set("travels_everywhere")} data-testid="provider-everywhere" />Se déplace partout (frais en sus)</label>

          <H>Conditions — 1. Prix</H>
          <Field label={`Tarif de base (€ ${subject ? "HT" : "net"})`}><Input type="number" min={0} step="0.01" value={f.base_rate} onChange={set("base_rate")} data-testid="provider-base-rate" /></Field>
          <Field label="Durée incluse (h)"><Input type="number" min={0} step="0.5" value={f.included_hours} onChange={set("included_hours")} data-testid="provider-included-hours" /></Field>
          <Field label="Heure supplémentaire (€)"><Input type="number" min={0} step="0.01" value={f.extra_hour_rate} onChange={set("extra_hour_rate")} data-testid="provider-extra-hour" /></Field>
          <div />
          <H>2. Déplacement</H>
          <Field label="Mode"><Pick value={f.travel_fee_mode} onChange={set("travel_fee_mode")} options={TRAVEL} testid="provider-travel-mode" /></Field>
          {["flat", "per_km"].includes(f.travel_fee_mode) ? <Field label={f.travel_fee_mode === "flat" ? "Forfait (€)" : "Tarif au km (€)"}><Input type="number" min={0} step="0.01" value={f.travel_fee_amount} onChange={set("travel_fee_amount")} data-testid="provider-travel-amount" /></Field> : <div />}
          {f.travel_fee_mode === "per_km" && <Field label="Km inclus (aller-retour)"><Input type="number" min={0} value={f.travel_km_included} onChange={set("travel_km_included")} data-testid="provider-km-included" /></Field>}
          <label className="flex items-center gap-3 self-end pb-2 text-sm"><Switch checked={f.meal_lodging} onCheckedChange={set("meal_lodging")} />Défraiement repas / hébergement si fin tardive</label>
          {f.meal_lodging && <Field label="Montant du défraiement (€)"><Input type="number" min={0} value={f.meal_lodging_fee} onChange={set("meal_lodging_fee")} /></Field>}
          <H>3. TVA</H>
          <Field label="Régime"><Pick value={f.vat_mode} onChange={set("vat_mode")} options={{ subject: "Assujetti TVA (prix HT)", not_applicable_293B: "Non assujetti (prix net)" }} testid="provider-vat-mode" /></Field>
          {subject ? <Field label="Taux de TVA (%)"><Input type="number" min={0} step="0.1" value={f.vat_rate} onChange={set("vat_rate")} data-testid="provider-vat-rate" /></Field> : <div />}
          <Field label="Statut juridique"><Pick value={f.legal_status} onChange={set("legal_status")} options={LEGAL} testid="provider-legal-status" /></Field>
          <p className="self-end pb-2 text-sm text-muted-foreground" data-testid="provider-price-summary">{subject ? `${fmtEur2(rate)} HT, soit ${fmtEur2(rate * (1 + (Number(f.vat_rate) || 0) / 100))} TTC` : `${fmtEur2(rate)} net — ${NOT_SUBJECT}`}</p>
          <H>4. Besoin matériel</H>
          <Field label="Ce qu'il apporte" className="col-span-2"><Input value={f.equipment_brought} onChange={set("equipment_brought")} placeholder="Sax + micro HF" data-testid="provider-equipment-brought" /></Field>
          <Field label="À lui fournir sur place" className="col-span-2"><Chips options={Object.entries(EQUIP)} value={f.equipment_needed} onChange={set("equipment_needed")} testid="provider-equipment-needed" /></Field>
          <Field label="Précisions matériel"><Input value={f.equipment_needed_note} onChange={set("equipment_needed_note")} /></Field>
          <Field label="Fiche technique (PDF)"><div className="flex items-center gap-2">
            {f.tech_rider && <button type="button" className="text-sm underline" onClick={() => openFile(f.tech_rider)}>Voir</button>}
            {f.tech_rider && <button type="button" className="text-sm underline" onClick={() => setF({ ...f, tech_rider: "" })}>Retirer</button>}
            <UploadButton accept="application/pdf" multiple={false} label={f.tech_rider ? "Remplacer" : "Téléverser"} testid="provider-tech-rider" onUploaded={(r) => setF((cur) => ({ ...cur, tech_rider: r[0] }))} /></div></Field>

          <H>Suivi interne</H>
          <Field label="Langue de communication (e-mails, page de réponse)"><LanguageSelect value={f.language} onChange={set("language")} testid="provider-language-select" /></Field>
          <Field label="Langues parlées"><ListInput value={f.languages} onChange={set("languages")} data-testid="provider-languages" /></Field>
          <Field label="Statut"><Pick value={f.status} onChange={set("status")} options={P_STATUS} testid="provider-status" /></Field>
          <Field label="Note interne (1 à 5)"><Pick value={f.rating} onChange={(v) => setF({ ...f, rating: Number(v) })} options={{ 0: "Non noté", 1: "1", 2: "2", 3: "3", 4: "4", 5: "5" }} testid="provider-rating" /></Field>
          <Field label="Notes privées" className="col-span-2"><Textarea rows={2} value={f.notes} onChange={set("notes")} data-testid="provider-notes" /></Field>
          <DialogFooter className="col-span-2"><Button type={inline ? "button" : "submit"} onClick={inline ? submit : undefined} disabled={busy} data-testid="provider-save-button">{busy ? "Enregistrement…" : "Enregistrer"}</Button></DialogFooter>
        </Tag>
  );
  if (inline) return open ? (
    <div data-testid="provider-inline-panel">
      <div className="mb-4 flex items-center gap-3"><h3 className="flex-1 text-lg font-semibold">Nouveau prestataire</h3><Button type="button" variant="ghost" onClick={() => onOpenChange(false)} data-testid="provider-inline-back">Retour à l'événement</Button></div>
      {form}
    </div>
  ) : null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto" data-testid="provider-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl font-medium">{provider ? "Modifier le prestataire" : "Nouveau prestataire"}</DialogTitle></DialogHeader>
        {form}
      </DialogContent>
    </Dialog>
  );
}
