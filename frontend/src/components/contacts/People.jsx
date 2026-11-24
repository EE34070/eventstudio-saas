import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Mail, MessageCircle, Phone, Plus, Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const BLANK = { first_name: "", last_name: "", role_label: "", phone: "", email: "", whatsapp: false, language: "", preferred_channel: "email", is_primary: false, cc_by_default: false, active: true, notes: "" };
const CH = { email: "E-mail", whatsapp: "WhatsApp", phone: "Téléphone" };

export function PeopleBlock({ contactId, write }) {
  const [d, setD] = useState(null);
  const [f, setF] = useState(null);
  const load = useCallback(() => api.get(`/contacts/${contactId}/people`).then((r) => setD(r.data)).catch(ko), [contactId]);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const set = (k, v) => setF({ ...f, [k]: v });
  const save = () => (f.id ? api.put(`/contact-people/${f.id}`, f) : api.post(`/contacts/${contactId}/people`, f)).then((r) => { setD(r.data); setF(null); toast.success("Personne enregistrée"); }).catch(ko);
  const t = (k, ph, tid) => <Input placeholder={ph} value={f[k] || ""} onChange={(e) => set(k, e.target.value)} data-testid={tid} />;
  const chk = (k, l, tid) => <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!f[k]} onChange={(e) => set(k, e.target.checked)} data-testid={tid} />{l}</label>;
  return (
    <div data-testid="people-block"><div className="eyebrow mb-2">Personnes ({d.people.length})</div>
      <div className="space-y-2">{d.people.map((p) => (
        <div key={p.id} className={`rounded-xl border border-border p-3 text-sm ${p.active ? "" : "opacity-60"}`} data-testid={`person-card-${p.id}`}>
          <div className="flex flex-wrap items-center gap-2">{p.is_primary && <Star className="h-4 w-4 fill-amber-400 text-amber-500" data-testid={`person-primary-${p.id}`} />}<b data-testid={`person-name-${p.id}`}>{p.name}</b>
            <span className="rounded-full bg-secondary px-2 py-0.5 text-xs" data-testid={`person-role-${p.id}`}>{p.role_label}</span>
            {p.cc_by_default && <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-xs text-sky-700">en copie</span>}{!p.active && <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs text-red-700" data-testid={`person-left-${p.id}`}>a quitté la structure</span>}
            <span className="flex-1" />
            {p.phone && <a href={`tel:${p.phone}`} aria-label="Appeler" data-testid={`person-call-${p.id}`}><Phone className="h-4 w-4" /></a>}
            {p.email && <a href={`mailto:${p.email}`} aria-label="E-mail" data-testid={`person-mail-${p.id}`}><Mail className="h-4 w-4" /></a>}
            {p.whatsapp && p.phone && <a href={`https://wa.me/${p.phone.replace(/\D/g, "")}`} target="_blank" rel="noreferrer" aria-label="WhatsApp" data-testid={`person-wa-${p.id}`}><MessageCircle className="h-4 w-4" /></a>}
            {write && <><button className="text-xs underline" onClick={() => setF({ ...BLANK, ...p })} data-testid={`person-edit-${p.id}`}>Modifier</button>
              <button aria-label="Supprimer" onClick={() => window.confirm("Supprimer cette personne ?") && api.delete(`/contact-people/${p.id}`).then((r) => setD(r.data)).catch(ko)} data-testid={`person-delete-${p.id}`}><Trash2 className="h-4 w-4" /></button></>}</div>
          <div className="mt-1 text-xs text-muted-foreground">{[p.phone, p.email, `préfère : ${CH[p.preferred_channel] || "E-mail"}`, p.notes].filter(Boolean).join(" · ")}</div>
        </div>))}</div>
      {f ? <div className="mt-2 grid grid-cols-2 gap-2 rounded-xl border border-primary/40 p-3" data-testid="person-form">
        {t("first_name", "Prénom", "person-first-name")}{t("last_name", "Nom *", "person-last-name")}
        <div><Input list="person-roles" placeholder="Rôle *" value={f.role_label} onChange={(e) => set("role_label", e.target.value)} data-testid="person-role-input" /><datalist id="person-roles">{d.roles.map((r) => <option key={r} value={r} />)}</datalist></div>
        <select className={sel} value={f.preferred_channel} onChange={(e) => set("preferred_channel", e.target.value)} data-testid="person-channel">{Object.entries(CH).map(([k, l]) => <option key={k} value={k}>Canal préféré : {l}</option>)}</select>
        {t("phone", "Téléphone", "person-phone")}{t("email", "E-mail", "person-email")}
        <div className="col-span-2">{t("notes", "Notes", "person-notes")}</div>
        <div className="col-span-2 flex flex-wrap items-center gap-3">{chk("whatsapp", "WhatsApp", "person-whatsapp")}{chk("is_primary", "Contact principal", "person-is-primary")}{chk("cc_by_default", "En copie par défaut", "person-cc")}{chk("active", "Actif (décocher : a quitté la structure)", "person-active")}
          <span className="flex-1" /><Button size="sm" variant="ghost" onClick={() => setF(null)}>Annuler</Button><Button size="sm" disabled={!f.last_name.trim() || !f.role_label.trim()} onClick={save} data-testid="person-save">Enregistrer</Button></div></div>
        : write && <button className="mt-2 text-sm underline" onClick={() => setF({ ...BLANK })} data-testid="person-add"><Plus className="mr-1 inline h-3.5 w-3.5" />Ajouter une personne</button>}
    </div>);
}

export function CategoriesField({ contact, onSaved }) {
  const [cats, setCats] = useState([]);
  const [v, setV] = useState(contact.categories.map((k) => k.key));
  useEffect(() => { api.get("/provider-categories").then((r) => setCats(r.data.filter((c) => c.active !== false))).catch(() => {}); }, []);
  if (!cats.length) return null;
  const toggle = (k) => { const n = v.includes(k) ? v.filter((x) => x !== k) : [...v, k]; if (!n.length) { toast.error("Au moins un métier est obligatoire"); return; } setV(n); api.put(`/contacts/${contact.id}/categories`, { categories: n }).then(() => onSaved?.()).catch(ko); };
  return (<div className="col-span-2" data-testid="contact-categories"><div className="mb-1 text-xs text-muted-foreground">Métier(s) * — enregistré dès le clic</div>
    <div className="flex flex-wrap gap-1.5">{cats.map((c) => <button type="button" key={c.key} aria-pressed={v.includes(c.key)} onClick={() => toggle(c.key)} data-testid={`contact-category-${c.key}`} className={`h-8 rounded-full border px-3 text-xs font-medium ${v.includes(c.key) ? "border-primary bg-primary text-white" : "border-border"}`}>{c.label}</button>)}</div></div>);
}

export function PlannerPersonFields({ f, setF }) {
  const [people, setPeople] = useState([]);
  useEffect(() => { if (f.planner_contact_id) api.get(`/contacts/${f.planner_contact_id}/people`).then((r) => setPeople(r.data.people.filter((p) => p.active || p.id === f.planner_person_id))).catch(() => setPeople([])); }, [f.planner_contact_id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!people.length) return null;
  const cc = f.planner_cc_person_ids || [];
  return (<div className="col-span-2 space-y-2" data-testid="planner-person-fields">
    <label className="block text-xs text-muted-foreground">Interlocuteur sur cet événement
      <select className={`${sel} mt-1 w-full`} value={f.planner_person_id || ""} onChange={(e) => setF({ ...f, planner_person_id: e.target.value || null })} data-testid="event-planner-person"><option value="">Contact principal (par défaut)</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name} — {p.role_label}</option>)}</select></label>
    <div className="flex flex-wrap items-center gap-3 text-xs"><span className="text-muted-foreground">Autres personnes en copie :</span>{people.filter((p) => p.id !== f.planner_person_id).map((p) => <label key={p.id} className="flex items-center gap-1"><input type="checkbox" checked={cc.includes(p.id)} onChange={(e) => setF({ ...f, planner_cc_person_ids: e.target.checked ? [...cc, p.id] : cc.filter((x) => x !== p.id) })} data-testid={`event-planner-cc-${p.id}`} />{p.name}</label>)}</div></div>);
}
