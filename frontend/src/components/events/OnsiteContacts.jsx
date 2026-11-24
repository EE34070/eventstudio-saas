import { useState } from "react";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Mail, MessageCircle, Phone, Plus, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { LanguageSelect } from "@/lib/i18n";
import { useMe } from "@/context/MeContext";

const BLANK = { id: "", name: "", role: "", phone: "", email: "", notes: "", is_primary: false, language: "fr-FR" };
const act = "inline-flex h-8 items-center gap-1.5 rounded-full border border-border px-3 text-xs font-medium hover:bg-secondary";
const wa = (phone) => { const d = String(phone || "").replace(/\D/g, ""); return d.startsWith("0") ? `33${d.slice(1)}` : d; };
const sorted = (cs) => [...cs].sort((a, b) => Number(b.is_primary) - Number(a.is_primary));

export function OnsiteEditor({ value, onChange }) {
  const patch = (i, k, v) => onChange(value.map((c, n) => (n === i ? { ...c, [k]: v } : c)));
  const move = (i, d) => { const next = [...value]; [next[i], next[i + d]] = [next[i + d], next[i]]; onChange(next); };
  const remove = (i) => { const next = value.filter((_, n) => n !== i); if (next.length && !next.some((c) => c.is_primary)) next[0] = { ...next[0], is_primary: true }; onChange(next); };
  return (
    <div data-testid="onsite-editor">
      <div className="mb-2 text-sm font-medium">Contacts sur place</div>
      {value.map((c, i) => (
        <div key={i} className="mb-2 rounded-xl border border-border p-3" data-testid={`onsite-row-${i}`}>
          <div className="grid grid-cols-2 gap-2">
            <Input required placeholder="Nom *" value={c.name} onChange={(e) => patch(i, "name", e.target.value)} data-testid={`onsite-name-${i}`} />
            <Input placeholder="Fonction (régisseur, traiteur…)" value={c.role} onChange={(e) => patch(i, "role", e.target.value)} data-testid={`onsite-role-${i}`} />
            <Input type="tel" placeholder="Téléphone" value={c.phone} onChange={(e) => patch(i, "phone", e.target.value)} data-testid={`onsite-phone-${i}`} />
            <Input type="email" placeholder="E-mail" value={c.email} onChange={(e) => patch(i, "email", e.target.value)} data-testid={`onsite-email-${i}`} />
            <Input className="col-span-2" placeholder="Notes (horaires de disponibilité…)" value={c.notes} onChange={(e) => patch(i, "notes", e.target.value)} />
            <LanguageSelect className="col-span-2" value={c.language} onChange={(v) => patch(i, "language", v)} testid={`onsite-language-${i}`} />
          </div>
          <div className="mt-2 flex items-center gap-3 text-xs">
            <label className="flex items-center gap-1.5"><input type="radio" checked={!!c.is_primary} onChange={() => onChange(value.map((x, n) => ({ ...x, is_primary: n === i })))} data-testid={`onsite-primary-${i}`} />Principal</label>
            <span className="flex-1" />
            <button type="button" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Monter" data-testid={`onsite-up-${i}`}><ArrowUp className="h-4 w-4" /></button>
            <button type="button" disabled={i === value.length - 1} onClick={() => move(i, 1)} aria-label="Descendre" data-testid={`onsite-down-${i}`}><ArrowDown className="h-4 w-4" /></button>
            <button type="button" onClick={() => remove(i)} aria-label="Supprimer ce contact" data-testid={`onsite-remove-${i}`}><Trash2 className="h-4 w-4" /></button>
          </div>
        </div>
      ))}
      {value.length < 12 && <button type="button" className="inline-flex items-center gap-1 text-sm font-semibold underline" onClick={() => onChange([...value, { ...BLANK, is_primary: !value.length }])} data-testid="onsite-add"><Plus className="h-4 w-4" />Ajouter un contact sur place</button>}
    </div>
  );
}

function Row({ c, children }) {
  return (
    <div className="border-b border-border py-2.5 last:border-b-0" data-testid={`onsite-contact-${c.id}`}>
      <div className="flex flex-wrap items-center gap-2">{children}<span className="font-medium">{c.name}</span>{c.role && <span className="text-muted-foreground">· {c.role}</span>}
        {c.is_primary && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">Principal</span>}</div>
      {(c.phone || c.email || c.notes) && <div className="mt-0.5 text-xs text-muted-foreground">{[c.phone, c.email, c.notes].filter(Boolean).join(" · ")}</div>}
      <div className="mt-1.5 flex flex-wrap gap-2">
        {c.phone && <a className={act} href={`tel:${c.phone}`}><Phone className="h-3.5 w-3.5" />Appeler</a>}
        {c.email && <a className={act} href={`mailto:${c.email}`}><Mail className="h-3.5 w-3.5" />E-mail</a>}
        {c.phone && <a className={act} href={`https://wa.me/${wa(c.phone)}`} target="_blank" rel="noreferrer"><MessageCircle className="h-3.5 w-3.5" />WhatsApp</a>}
      </div>
    </div>
  );
}

export const OnsiteList = ({ contacts }) => (
  <div className="text-sm" data-testid="onsite-list"><div className="eyebrow mb-1">Contacts sur place</div>
    {contacts.length ? sorted(contacts).map((c) => <Row key={c.id} c={c} />) : <div className="text-muted-foreground">Aucun contact sur place.</div>}</div>
);

export function OnsiteCard({ ev }) {
  const { can } = useMe();
  const [sel, setSel] = useState(ev.onsite_selected || []);
  const contacts = ev.venue?.onsite_contacts || [];
  if (!contacts.length) return null;
  const toggle = async (id) => {
    const next = sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id];
    setSel(next);
    try { const r = await api.patch(`/events/${ev.id}`, { onsite_contact_ids: next }); setSel(r.data.onsite_selected || next); } catch (e) { setSel(sel); toast.error(errMsg(e)); }
  };
  return (
    <div className="border-t border-border pt-3" data-testid="event-onsite-contacts">
      <div className="eyebrow mb-1">Contacts sur place — cochez ceux de cet événement</div>
      {sorted(contacts).map((c) => <Row key={c.id} c={c}><input type="checkbox" checked={sel.includes(c.id)} disabled={!can("events:write")} onChange={() => toggle(c.id)} aria-label={`${c.name} est sur place pour cet événement`} data-testid={`event-onsite-check-${c.id}`} /></Row>)}
    </div>
  );
}
