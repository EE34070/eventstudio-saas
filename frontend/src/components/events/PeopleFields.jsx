import { useState } from "react";
import { Link } from "react-router-dom";
import { Mail, MessageCircle, Phone, Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Field, Section } from "@/components/common";
import { PlannerPersonFields } from "@/components/contacts/People";
import { useMe } from "@/context/MeContext";

const norm = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

function Combo({ options, onPick, placeholder, testid, createLabel, onCreate }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const shown = options.filter((o) => norm(`${o.label} ${o.sub}`).includes(norm(q))).slice(0, 8);
  return (
    <div className="relative">
      <Input value={q} placeholder={placeholder} autoComplete="off" data-testid={testid} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)} />
      {open && (shown.length > 0 || (onCreate && q.trim())) && (
        <ul className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-md" data-testid={`${testid}-options`}>
          {shown.map((o) => (
            <li key={o.id} className="cursor-pointer rounded-lg px-3 py-2 text-sm hover:bg-secondary" data-testid={`${testid}-option-${o.id}`} onMouseDown={(e) => { e.preventDefault(); setQ(""); setOpen(false); onPick(o.id); }}>
              <div className="font-medium">{o.label}</div>{o.sub && <div className="text-xs text-muted-foreground">{o.sub}</div>}
            </li>
          ))}
          {onCreate && q.trim() && <li className="cursor-pointer rounded-lg px-3 py-2 text-sm font-semibold text-primary hover:bg-secondary" data-testid={`${testid}-create`} onMouseDown={(e) => { e.preventDefault(); setOpen(false); onCreate(q.trim()); setQ(""); }}>{createLabel(q.trim())}</li>}
        </ul>
      )}
    </div>
  );
}

export function PeopleFields({ f, setF, contacts, planners, fin, canCreate, onCreatePlanner }) {
  const [adding, setAdding] = useState(false);
  const ids = f.client_contact_ids;
  const byId = Object.fromEntries(contacts.map((c) => [c.id, c]));
  const planner = planners.find((p) => p.contact_id === f.planner_contact_id);
  const setClients = (next, sig = f.signatory_contact_id) => setF({ ...f, client_contact_ids: next, signatory_contact_id: next.includes(sig) ? sig : next[0] || "" });
  return (
    <div className="grid grid-cols-1 gap-4 sm:col-span-2 sm:grid-cols-2" data-testid="event-people">
      <Field label="Client (signataire)">
        {ids.map((id) => (
          <div key={id} className="mb-2 flex items-center gap-2 rounded-xl border border-border px-3 py-2 text-sm" data-testid={`event-client-${id}`}>
            <span className="min-w-0 flex-1 truncate font-medium">{byId[id]?.label || "Contact"}</span>
            <label className="flex items-center gap-1.5 whitespace-nowrap text-xs"><input type="radio" name="signatory" checked={f.signatory_contact_id === id} onChange={() => setF({ ...f, signatory_contact_id: id })} data-testid={`event-signatory-${id}`} />Signataire du contrat</label>
            <button type="button" aria-label="Retirer ce client" onClick={() => setClients(ids.filter((x) => x !== id))} data-testid={`event-client-remove-${id}`}><X className="h-4 w-4" /></button>
          </div>
        ))}
        {(!ids.length || adding) ? <Combo testid="event-client-search" placeholder="Rechercher un client…" options={contacts.filter((c) => c.client && !ids.includes(c.id))} onPick={(id) => { setClients([...ids, id]); setAdding(false); }} />
          : ids.length < 6 && <button type="button" className="inline-flex items-center gap-1 text-sm font-semibold underline" onClick={() => setAdding(true)} data-testid="event-client-add"><Plus className="h-4 w-4" />Ajouter un client</button>}
      </Field>
      <Field label="Organisateur (optionnel)">
        {planner || f.planner_contact_id ? (
          <div className="flex items-center gap-2 rounded-xl border border-border px-3 py-2 text-sm" data-testid="event-planner-selected">
            <span className="min-w-0 flex-1 truncate font-medium">{planner?.display_name || "Organisateur"}{planner?.city ? <span className="font-normal text-muted-foreground"> · {planner.city}</span> : null}</span>
            <button type="button" aria-label="Retirer l'organisateur" onClick={() => setF({ ...f, planner_contact_id: "", main_contact_role: "client" })} data-testid="event-planner-remove"><X className="h-4 w-4" /></button>
          </div>
        ) : <Combo testid="event-planner-search" placeholder="Rechercher un organisateur…" options={planners.map((p) => ({ id: p.contact_id, label: p.display_name, sub: [p.type_label, p.company, p.city].filter(Boolean).join(" · ") }))}
          onPick={(id) => setF({ ...f, planner_contact_id: id, main_contact_role: "planner" })} createLabel={(t) => `+ Créer l'organisateur « ${t} »`} onCreate={canCreate ? onCreatePlanner : undefined} />}
      </Field>
      {f.planner_contact_id && (<>
        <PlannerPersonFields f={f} setF={setF} />
        <Field label="Interlocuteur principal">
          <Select value={f.main_contact_role} onValueChange={(v) => setF({ ...f, main_contact_role: v })}><SelectTrigger data-testid="event-main-contact"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="planner">Organisateur</SelectItem><SelectItem value="client">Client</SelectItem></SelectContent></Select>
        </Field>
        {fin && (
          <Field label="Commission organisateur / apport d'affaires">
            <div className="flex gap-2">
              <Select value={f.planner_commission_mode} onValueChange={(v) => setF({ ...f, planner_commission_mode: v })}><SelectTrigger data-testid="event-commission-mode"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="none">Aucune</SelectItem><SelectItem value="percent">% du HT</SelectItem><SelectItem value="fixed">Montant fixe (€)</SelectItem></SelectContent></Select>
              {f.planner_commission_mode !== "none" && <Input type="number" min={0} step="0.01" className="w-24" value={f.planner_commission_value} onChange={(e) => setF({ ...f, planner_commission_value: e.target.value })} data-testid="event-commission-value" />}
              {f.planner_commission_mode !== "none" && <Select value={f.planner_commission_status} onValueChange={(v) => setF({ ...f, planner_commission_status: v })}><SelectTrigger className="w-32" data-testid="event-commission-status"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="due">À verser</SelectItem><SelectItem value="paid">Versée</SelectItem></SelectContent></Select>}
            </div>
          </Field>
        )}
      </>)}
      <p className="text-xs text-muted-foreground sm:col-span-2">Devis, contrat et factures sont adressés au client signataire. L'interlocuteur principal est le contact par défaut pour l'organisation au quotidien.</p>
    </div>
  );
}

const wa = (phone) => { const d = String(phone || "").replace(/\D/g, ""); return d.startsWith("0") ? `33${d.slice(1)}` : d; };
const act = "inline-flex h-9 items-center gap-1.5 rounded-full border border-border px-3 text-xs font-medium hover:bg-secondary";
const Tag = ({ children, testid }) => <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary" data-testid={testid}>{children}</span>;

function Person({ c, tags, link, testid }) {
  return (
    <div className="border-b border-border pb-3 last:border-b-0 last:pb-0" data-testid={testid}>
      <div className="flex flex-wrap items-center gap-2">{link ? <Link to={link} className="font-medium hover:underline">{c.display_name}</Link> : <span className="font-medium">{c.display_name}</span>}{tags}</div>
      <div className="mt-1 text-sm text-muted-foreground">{[c.phone, c.email].filter(Boolean).join(" · ") || "Coordonnées non renseignées"}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {c.phone && <a className={act} href={`tel:${c.phone}`} data-testid={`${testid}-call`}><Phone className="h-3.5 w-3.5" />Appeler</a>}
        {c.email && <a className={act} href={`mailto:${c.email}`} data-testid={`${testid}-email`}><Mail className="h-3.5 w-3.5" />E-mail</a>}
        {c.phone && <a className={act} href={`https://wa.me/${wa(c.phone)}`} target="_blank" rel="noreferrer" data-testid={`${testid}-whatsapp`}><MessageCircle className="h-3.5 w-3.5" />WhatsApp</a>}
      </div>
    </div>
  );
}

export function PeopleCards({ ev }) {
  const { can } = useMe();
  const main = <Tag testid="main-contact-badge">Interlocuteur principal</Tag>;
  const com = ev.planner_commission_mode && ev.planner_commission_mode !== "none";
  return (<>
    <Section title="Client" testid="infos-client">
      {ev.clients?.length ? <div className="space-y-3">{ev.clients.map((c) => <Person key={c.id} c={c} testid={`client-card-${c.id}`}
        tags={<>{c.is_signatory && <Tag>Signataire du contrat</Tag>}{c.is_signatory && ev.main_contact_role === "client" && main}</>} />)}</div>
        : <div className="text-sm text-muted-foreground">{ev.client_id ? "Coordonnées client non visibles pour votre rôle." : "Aucun client associé."}</div>}
    </Section>
    <Section title="Organisateur" testid="infos-planner">
      {ev.planner ? (<>
        <Person c={ev.planner} testid="planner-card" link={can("providers:manage") && ev.planner.provider_id ? `/prestataires?id=${ev.planner.provider_id}` : null} tags={<>{(ev.planner.types || []).map((t) => <Tag key={t} testid="organizer-type-badge">{t}</Tag>)}{ev.main_contact_role === "planner" && main}</>} />
        {ev.planner.person && <div className="mt-2 text-sm" data-testid="planner-person-card">Interlocuteur : <b>{ev.planner.person.name}</b> — {ev.planner.person.role_label}{ev.planner.person.active === false ? " (a quitté la structure)" : ""}{ev.planner.person.phone ? <> · <a className="underline" href={`tel:${ev.planner.person.phone}`}>{ev.planner.person.phone}</a></> : null}{ev.planner.person.email ? <> · <a className="underline" href={`mailto:${ev.planner.person.email}`}>{ev.planner.person.email}</a></> : null}
          {ev.planner.cc?.length > 0 && <div className="text-xs text-muted-foreground" data-testid="planner-cc">En copie : {ev.planner.cc.map((p) => `${p.name} (${p.role_label})`).join(", ")}</div>}</div>}
        {com && <div className="mt-3 text-sm" data-testid="planner-commission">Commission : {ev.planner_commission_mode === "percent" ? `${String(ev.planner_commission_value).replace(".", ",")} % du HT` : `${ev.planner_commission_value} €`} — {ev.planner_commission_status === "paid" ? "versée" : "à verser"}</div>}
      </>) : <div className="text-sm text-muted-foreground">{ev.planner_contact_id ? "Coordonnées non visibles pour votre rôle." : "Aucun organisateur sur cet événement."}</div>}
    </Section>
  </>);
}
