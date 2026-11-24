import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Disc3, SlidersHorizontal, Camera, Aperture, Heart, Briefcase, Boxes } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Field, Section, Loading } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { TranslateButton } from "@/lib/i18n";
import { MODULES, EVENT_TYPES } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

const ICONS = { dj: Disc3, son_lumiere: SlidersHorizontal, photobooth: Camera, photographe: Aperture, wedding_planner: Heart, agence: Briefcase, loueur_materiel: Boxes };
const DESC = {
  dj: "Style musical, playlists, déroulé de soirée, options sax / MC.",
  son_lumiere: "Fiche technique, besoins électriques, plans d'implantation et de feu.",
  photobooth: "Type de borne, template, tirages, galerie en ligne, accessoires.",
  photographe: "Shot list, moments clés, délai et lien de galerie.",
  wedding_planner: "Rétroplanning, budget prévisionnel / réel, prestataires, check-list mariés.",
  agence: "Multi-prestataires, budget client vs coûts, marge, sous-traitance.",
  loueur_materiel: "Réservation du stock par période, cautions, état au départ et au retour.",
};
const FIELDS = [["name", "Nom commercial"], ["legal_name", "Raison sociale"], ["siret", "SIRET"], ["vat_number", "N° TVA intracommunautaire"], ["address", "Adresse"], ["zip", "Code postal"], ["city", "Ville"], ["phone", "Téléphone"], ["email", "E-mail"], ["website", "Site web"], ["logo_url", "Logo (URL)"], ["iban", "IBAN"], ["bic", "BIC"]];

function OrgForm({ write }) {
  const { reload } = useMe();
  const [f, setF] = useState(null);
  useEffect(() => { api.get("/org").then((r) => setF(r.data)); }, []);
  if (!f) return <Loading />;
  const save = async () => {
    const body = Object.fromEntries([...FIELDS.map(([k]) => k), "legal_form_capital", "rcs", "ape", "licence", "mediator", "legal_mentions", "payment_terms", "terms", "legal_mentions_en", "payment_terms_en", "terms_en"].map((k) => [k, f[k] ?? ""]));
    body.quote_validity_days = Number(f.quote_validity_days) || 30; body.balance_days = Number(f.balance_days) || 15;
    body.terms_annex = f.terms_annex !== false;
    body.signature_fields = (f.signature_fields || []).map((x) => x.trim()).filter(Boolean).slice(0, 6);
    body.signature_fields_en = (f.signature_fields_en || []).map((x) => x.trim()).filter(Boolean).slice(0, 6);
    body.default_vat = Number(body.default_vat) || 0; body.deposit_percent = Number(body.deposit_percent) || 0;
    try { await api.put("/org", body); toast.success("Organisation enregistrée"); reload(); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Section testid="org-form">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {FIELDS.map(([k, l]) => <Field key={k} label={l}><Input disabled={!write} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`org-${k}-input`} /></Field>)}
        <Field label="Conditions de paiement" className="sm:col-span-2"><Textarea disabled={!write} rows={3} value={f.payment_terms || ""} onChange={(e) => setF({ ...f, payment_terms: e.target.value })} /></Field>
        <Field label="Validité d'un devis (jours)"><Input type="number" min="1" disabled={!write} value={f.quote_validity_days ?? 30} onChange={(e) => setF({ ...f, quote_validity_days: e.target.value })} data-testid="org-quote-validity" /></Field>
        <Field label="Solde dû : jours avant l'événement"><Input type="number" min="0" disabled={!write} value={f.balance_days ?? 15} onChange={(e) => setF({ ...f, balance_days: e.target.value })} data-testid="org-balance-days" /></Field>
        <Field label="Mentions légales complémentaires (bas de devis / facture)" className="sm:col-span-2"><Textarea disabled={!write} rows={3} value={f.legal_mentions || ""} onChange={(e) => setF({ ...f, legal_mentions: e.target.value })} /></Field>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Field label="Conditions générales (jointes au devis et signées avec lui)"><Textarea disabled={!write} rows={8} value={f.terms || ""} onChange={(e) => setF({ ...f, terms: e.target.value })} data-testid="org-terms-input" /></Field>
        <Field label="Champs que le client remplit à la signature (un par ligne, 6 maximum)"><Textarea disabled={!write} rows={8} value={(f.signature_fields || ["Nom et qualité du signataire", "Adresse de facturation", "Mention « Bon pour accord »"]).join("\n")} onChange={(e) => setF({ ...f, signature_fields: e.target.value.split("\n") })} data-testid="org-signature-fields-input" /></Field>
      </div>
      <div className="mt-4 rounded-2xl border border-border p-4 text-sm" data-testid="org-cgv-block"><div className="font-medium">CGV jointes aux devis</div><p className="text-muted-foreground">Français pour un devis en français, anglais pour toute autre langue. Si un PDF est importé, il remplace le texte saisi pour cette langue.</p>
        <label className="mt-2 flex items-center gap-2"><input type="checkbox" disabled={!write} checked={f.terms_annex !== false} onChange={(e) => setF({ ...f, terms_annex: e.target.checked })} data-testid="org-terms-annex" />Ajouter les CGV en annexe du PDF du devis</label>
        {[["fr", "CGV en français"], ["en", "CGV en anglais"]].map(([k, l]) => { const cur = f[`terms_file_${k}`]; return (
          <div key={k} className="mt-2 flex flex-wrap items-center gap-2" data-testid={`org-cgv-${k}`}><b>{l}</b><span className="text-muted-foreground">{cur ? cur.filename || "PDF importé" : (k === "fr" ? f.terms : f.terms_en) ? "texte saisi" : "aucune"}</span>
            {write && <><input type="file" accept="application/pdf" className="text-xs" onChange={(e) => { const x = e.target.files[0]; e.target.value = ""; if (!x) return; const fd = new FormData(); fd.append("file", x); api.post(`/org/terms-file?lang=${k}`, fd).then((r) => { setF((c) => ({ ...c, [`terms_file_${k}`]: r.data[`terms_file_${k}`] })); toast.success("CGV importées"); }).catch((err) => toast.error(errMsg(err))); }} data-testid={`org-cgv-file-${k}`} />
              {cur && <button type="button" className="text-xs underline" onClick={() => api.delete(`/org/terms-file?lang=${k}`).then(() => setF((c) => ({ ...c, [`terms_file_${k}`]: null }))).catch((err) => toast.error(errMsg(err)))} data-testid={`org-cgv-remove-${k}`}>retirer le PDF</button>}</>}</div>); })}</div>
      <div className="mt-6 rounded-2xl border border-border p-4" data-testid="org-english-block">
        <div className="mb-3 flex flex-wrap items-center gap-3"><div className="flex-1"><div className="font-medium">Version anglaise (documents des clients non francophones)</div><p className="text-sm text-muted-foreground">Le texte français reste la référence et est joint aux conditions générales anglaises. Champ vide = texte français utilisé.</p></div>
          {write && <TranslateButton testid="org-translate-button" label="Traduire le français (IA)" context="Textes juridiques et commerciaux de devis et factures."
            texts={{ payment_terms_en: f.payment_terms || "", legal_mentions_en: f.legal_mentions || "", terms_en: f.terms || "", signature_fields_en: (f.signature_fields || []).join("\n") }}
            onDone={(r) => setF((cur) => ({ ...cur, payment_terms_en: r.payment_terms_en, legal_mentions_en: r.legal_mentions_en, terms_en: r.terms_en, signature_fields_en: r.signature_fields_en.split("\n") }))} />}</div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Field label="Payment terms"><Textarea disabled={!write} rows={3} value={f.payment_terms_en || ""} onChange={(e) => setF({ ...f, payment_terms_en: e.target.value })} data-testid="org-payment-terms-en" /></Field>
          <Field label="Legal mentions"><Textarea disabled={!write} rows={3} value={f.legal_mentions_en || ""} onChange={(e) => setF({ ...f, legal_mentions_en: e.target.value })} data-testid="org-legal-mentions-en" /></Field>
          <Field label="Terms and conditions"><Textarea disabled={!write} rows={8} value={f.terms_en || ""} onChange={(e) => setF({ ...f, terms_en: e.target.value })} data-testid="org-terms-en" /></Field>
          <Field label="Signature fields (one per line)"><Textarea disabled={!write} rows={8} value={(f.signature_fields_en || []).join("\n")} onChange={(e) => setF({ ...f, signature_fields_en: e.target.value.split("\n") })} data-testid="org-signature-fields-en" /></Field>
        </div>
      </div>
      {f.logo_url && <img src={f.logo_url} alt="Logo" className="mt-4 h-16 object-contain" />}
      {write && <div className="mt-5 flex justify-end"><Button onClick={save} data-testid="save-org-button">Enregistrer</Button></div>}
    </Section>
  );
}

function ModuleDefaults({ write }) {
  const { modules } = useMe();
  const key = modules.join(",");
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/modules").then((r) => setD(r.data)); }, [key]);
  if (!d) return null;
  const toggle = async (type, k) => {
    const cur = d.defaults[type] || [];
    const defaults = { ...d.defaults, [type]: cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k] };
    try { await api.put("/org/module-defaults", { defaults }); setD({ ...d, defaults }); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <div className="card-soft mt-6 p-5" data-testid="module-defaults">
      <div className="font-medium">Modules pré-sélectionnés par type d'événement</div>
      <p className="mt-1 text-sm text-muted-foreground">Cochés d'office dans « Nouvel événement » ; modifiables à chaque création.</p>
      <div className="mt-3 divide-y divide-border">
        {EVENT_TYPES.map((t) => (
          <div key={t} className="flex flex-wrap items-center gap-2 py-2.5"><span className="w-44 text-sm">{t}</span>
            {d.modules.map((m) => { const on = (d.defaults[t] || []).includes(m.key); return <button key={m.key} disabled={!write} aria-pressed={on} onClick={() => toggle(t, m.key)} data-testid={`module-default-${t}-${m.key}`} className={`h-8 rounded-full border px-3.5 text-xs font-medium ${on ? "border-primary bg-primary text-white" : "border-border"}`}>{m.label}</button>; })}
          </div>
        ))}
      </div>
    </div>
  );
}

function Modules({ write }) {
  const { modules, reload } = useMe();
  const toggle = async (id, on) => {
    const next = on ? [...modules, id] : modules.filter((m) => m !== id);
    try { await api.put("/org/modules", { modules: next }); await reload(); toast.success(on ? "Module activé" : "Module désactivé"); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="modules-grid">
      {MODULES.map((m) => {
        const I = ICONS[m.id];
        const on = modules.includes(m.id);
        return (
          <div key={m.id} className={`card-soft p-5 transition-colors ${on ? "ring-1 ring-primary/40" : ""}`} data-testid={`module-card-${m.id}`}>
            <div className="flex items-start justify-between">
              <span className={`flex h-10 w-10 items-center justify-center rounded-xl ${on ? "bg-primary text-white" : "bg-secondary text-muted-foreground"}`}><I className="h-5 w-5" /></span>
              <Switch disabled={!write} checked={on} onCheckedChange={(v) => toggle(m.id, v)} data-testid={`module-switch-${m.id}`} />
            </div>
            <div className="mt-3 font-medium">{m.label}</div>
            <p className="mt-1 text-sm text-muted-foreground">{DESC[m.id]}</p>
          </div>
        );
      })}
    </div>
  );
}

export { OrgForm, Modules as OrgModules, ModuleDefaults };
