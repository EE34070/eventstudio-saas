import { useEffect, useState } from "react";
import { MapPin, Pencil, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field } from "@/components/common";
import { OnsiteEditor } from "@/components/events/OnsiteContacts";

export const EMPTY_VENUE = { name: "", address: "", zip: "", city: "", lat: null, lng: null, contact_name: "", contact_phone: "", contact_email: "", onsite_contacts: [], access_instructions: "" };
const REQUIRED = ["name", "address", "zip", "city"];
export const venueComplete = (v) => !!v && ["address", "zip", "city"].every((k) => (v[k] || "").trim());
export const venueDraftOk = (d) => REQUIRED.every((k) => (d[k] || "").trim());
const norm = (s) => (s || "").trim().toLowerCase();

function Combo({ value, onText, options, onPick, onLeave, placeholder, testid, invalid }) {
  const [open, setOpen] = useState(false);
  const [i, setI] = useState(0);
  useEffect(() => { setI(0); }, [options.length]);
  const pick = (o) => { setOpen(false); onPick(o); };
  const key = (e) => {
    if (e.key === "Escape") { setOpen(false); return; }
    if (!open) return;
    if (e.key === "Enter") { e.preventDefault(); if (options[i]) pick(options[i]); return; }
    if (!options.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setI((i + 1) % options.length); }
    if (e.key === "ArrowUp") { e.preventDefault(); setI((i - 1 + options.length) % options.length); }
  };
  const shown = open && options.length > 0;
  return (
    <div className="relative">
      <Input value={value} placeholder={placeholder} autoComplete="off" role="combobox" aria-expanded={shown} aria-invalid={invalid || undefined} data-testid={testid}
        onChange={(e) => { onText(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onBlur={() => { setOpen(false); onLeave?.(); }} onKeyDown={key} />
      {shown && (
        <ul role="listbox" className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-md" data-testid={`${testid}-options`}>
          {options.map((o, n) => (
            <li key={o.key} role="option" aria-selected={n === i} onMouseDown={(e) => { e.preventDefault(); pick(o); }} onMouseEnter={() => setI(n)}
              className={`cursor-pointer rounded-lg px-3 py-2 text-sm ${n === i ? "bg-secondary" : ""}`} data-testid={`${testid}-option-${n}`}>
              <div className="font-medium">{o.label}</div>{o.sub && <div className="text-xs text-muted-foreground">{o.sub}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function VenueField({ label, venues, value, onChange, draft, onDraft, testid }) {
  const [q, setQ] = useState("");
  const [touched, setTouched] = useState({});
  const [addrQ, setAddrQ] = useState("");
  const [addr, setAddr] = useState([]);
  const sel = venues.find((v) => v.id === value);
  const n = norm(q);
  const hits = n.length >= 2 ? venues.filter((v) => norm(`${v.name} ${v.city} ${v.address}`).includes(n))
    .sort((a, b) => norm(b.name).startsWith(n) - norm(a.name).startsWith(n)).slice(0, 6) : [];
  const options = n.length < 2 ? [] : hits.length
    ? hits.map((v) => ({ key: v.id, label: v.name, sub: [v.address, v.city].filter(Boolean).join(", "), id: v.id }))
    : [{ key: "new", label: `+ Créer le lieu "${q.trim()}"` }];
  const start = () => { if (q.trim().length < 2) return; onDraft({ ...EMPTY_VENUE, name: q.trim() }); setQ(""); setTouched({}); };
  const set = (k) => (e) => onDraft({ ...draft, [k]: e.target.value });

  useEffect(() => {
    if (addrQ.trim().length < 4) { setAddr([]); return undefined; }
    const t = setTimeout(() => fetch(`https://data.geopf.fr/geocodage/search?limit=5&q=${encodeURIComponent(addrQ)}`).then((r) => r.json())
      .then((d) => setAddr((d.features || []).map((x, i) => ({ key: i, label: x.properties.name, sub: `${x.properties.postcode} ${x.properties.city}`, p: x.properties, c: x.geometry?.coordinates }))))
      .catch(() => setAddr([])), 250);
    return () => clearTimeout(t);
  }, [addrQ]);

  const dup = draft && draft.zip && venues.find((v) => norm(v.name) === norm(draft.name) && norm(v.zip) === norm(draft.zip));
  const bad = (k) => touched[k] && !(draft[k] || "").trim();
  const err = (k) => bad(k) && <span className="text-xs text-red-600 dark:text-red-400" data-testid={`${testid}-error-${k}`}>Champ obligatoire</span>;
  const blur = (k) => () => setTouched((t) => ({ ...t, [k]: true }));

  return (
    <div className="sm:col-span-2" data-testid={testid}>
      <Field label={label}>
        {sel ? (
          <div className="flex items-start gap-3 rounded-2xl border border-border p-4" data-testid={`${testid}-card`}>
            <MapPin className="mt-0.5 h-[18px] w-[18px] shrink-0" />
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-semibold">{sel.name}</div>
              <div className="text-muted-foreground">{[sel.address, [sel.zip, sel.city].filter(Boolean).join(" ")].filter(Boolean).join(", ") || "Adresse non renseignée"}</div>
              {(sel.contact_name || sel.contact_phone) && <div className="text-muted-foreground">Contact sur place : {[sel.contact_name, sel.contact_phone].filter(Boolean).join(" · ")}</div>}
            </div>
            <a href={`/lieux?id=${sel.id}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold underline" data-testid={`${testid}-edit`}><Pencil className="h-3.5 w-3.5" />Modifier</a>
            <button type="button" onClick={() => onChange("")} aria-label="Changer de lieu" data-testid={`${testid}-clear`}><X className="h-4 w-4" /></button>
          </div>
        ) : !draft ? (
          <Combo value={q} onText={setQ} options={options} placeholder="Rechercher un lieu (nom, ville, adresse)…" testid={`${testid}-search`}
            onPick={(o) => { if (o.id) { onChange(o.id); setQ(""); } else start(); }} onLeave={start} />
        ) : null}
      </Field>
      {draft && !sel && (
        <div className="mt-2 grid grid-cols-1 gap-3 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 sm:grid-cols-2" data-testid={`${testid}-new`}>
          <div className="flex items-center justify-between sm:col-span-2"><span className="text-sm font-semibold">Adresse du nouveau lieu</span>
            <button type="button" className="text-xs underline" onClick={() => onDraft(null)} data-testid={`${testid}-new-cancel`}>Annuler</button></div>
          {dup && <button type="button" className="rounded-xl border border-border bg-card p-3 text-left text-sm sm:col-span-2" onClick={() => { onChange(dup.id); onDraft(null); }} data-testid={`${testid}-duplicate`}>Ce lieu existe déjà : <b className="underline">l'utiliser ?</b> ({dup.name}, {dup.city})</button>}
          <Field label="Nom du lieu *" className="sm:col-span-2"><Input value={draft.name} onChange={set("name")} onBlur={blur("name")} aria-invalid={bad("name") || undefined} data-testid={`${testid}-new-name`} />{err("name")}</Field>
          <Field label="Adresse *" className="sm:col-span-2">
            <Combo value={draft.address} options={addr} testid={`${testid}-new-address`} invalid={bad("address")} placeholder="12 rue de la République"
              onText={(v) => { onDraft({ ...draft, address: v }); setAddrQ(v); }} onLeave={blur("address")}
              onPick={(o) => { onDraft({ ...draft, address: o.p.name, zip: o.p.postcode || draft.zip, city: o.p.city || draft.city, lat: o.c?.[1] ?? null, lng: o.c?.[0] ?? null }); setAddrQ(""); }} />{err("address")}
          </Field>
          <Field label="Code postal *"><Input value={draft.zip} onChange={set("zip")} onBlur={blur("zip")} aria-invalid={bad("zip") || undefined} data-testid={`${testid}-new-zip`} />{err("zip")}</Field>
          <Field label="Ville *"><Input value={draft.city} onChange={set("city")} onBlur={blur("city")} aria-invalid={bad("city") || undefined} data-testid={`${testid}-new-city`} />{err("city")}</Field>
          <div className="sm:col-span-2"><OnsiteEditor value={draft.onsite_contacts || []} onChange={(v) => onDraft({ ...draft, onsite_contacts: v })} /></div>
          <Field label="Instructions d'accès / livraison" className="sm:col-span-2"><Textarea rows={2} value={draft.access_instructions} onChange={set("access_instructions")} data-testid={`${testid}-new-instructions`} /></Field>
        </div>
      )}
    </div>
  );
}
