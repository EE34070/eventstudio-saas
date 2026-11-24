import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ClipboardPaste, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field, PageHeader, Section } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { EVENT_TYPES, fmtDate } from "@/lib/constants";
import { LanguageSelect } from "@/lib/i18n";
import { useMe } from "@/context/MeContext";

const SOURCES = { "": "Détection automatique", sms: "SMS", instagram: "Instagram", whatsapp: "WhatsApp", email: "Email", telephone: "Téléphone (notes)", autre: "Autre" };
const sel = "h-10 w-full rounded-lg border border-border bg-background px-3 text-sm";
const nowLocal = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const warn = "border-amber-500 ring-1 ring-amber-500";

function Paste({ onParsed }) {
  const [sp] = useSearchParams();
  const [f, setF] = useState({ raw_text: [sp.get("title"), sp.get("text"), sp.get("url")].filter(Boolean).join("\n"), source: "", received_at: nowLocal() });
  const [busy, setBusy] = useState(false);
  const paste = async () => { try { const t = await navigator.clipboard.readText(); setF((x) => ({ ...x, raw_text: x.raw_text ? `${x.raw_text}\n${t}` : t })); } catch { toast.error("Presse-papier non autorisé : collez le texte dans la zone"); } };
  const run = async () => { setBusy(true); try { onParsed((await api.post("/inbound-requests/parse", f)).data); } catch (e) { toast.error(errMsg(e), { duration: 12000 }); if (e.response?.status === 503) { try { onParsed((await api.post("/inbound-requests/parse", { ...f, manual: true })).data); } catch (x) { toast.error(errMsg(x)); } } } setBusy(false); };
  return (
    <Section testid="inbound-paste">
      {navigator.clipboard?.readText && <Button variant="outline" size="sm" className="mb-3" onClick={paste} data-testid="inbound-clipboard"><ClipboardPaste />Coller depuis le presse-papier</Button>}
      <Textarea autoFocus rows={10} placeholder="Collez ici le ou les messages reçus (SMS, Instagram, WhatsApp, email)…" value={f.raw_text} onChange={(e) => setF({ ...f, raw_text: e.target.value })} data-testid="inbound-text" />
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field label="Source"><select className={sel} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} data-testid="inbound-source">{Object.entries(SOURCES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Reçu le"><Input type="datetime-local" value={f.received_at} onChange={(e) => setF({ ...f, received_at: e.target.value })} data-testid="inbound-received" /></Field>
        <div className="flex items-end"><Button className="w-full" disabled={busy || !f.raw_text.trim()} onClick={run} data-testid="inbound-analyze"><Sparkles />{busy ? "Analyse…" : "Analyser"}</Button></div>
      </div>
    </Section>
  );
}

function Review({ req }) {
  const nav = useNavigate();
  const { can } = useMe();
  const x = req.extracted_json;
  const m = req.matches;
  const conf = x.confidence;
  const [c, setC] = useState({ ...x.client, use: m.client?.strong ? m.client.id : "" });
  const [o, setO] = useState({ ...x.organizer, use: m.organizer?.id || "" });
  const [e, setE] = useState({ title: x.event.title_suggestion, type: x.event.category || "Autre", date: x.event.date, start_time: x.event.start_time, end_time: x.event.end_time, guests: x.event.guests,
    venue_id: m.venue?.id || "", venue_name: x.event.venue_name, venue_address: x.event.venue_address, venue_zip: x.event.venue_postal_code, venue_city: x.event.venue_city, modules: x.event.modules,
    budget: x.event.budget_amount, budget_tax_mode: (x.event.budget_tax_mode || "TTC").toLowerCase() === "ht" ? "ht" : "ttc",
    notes: [x.notes, x.event.equipment_requested.length ? `Matériel demandé : ${x.event.equipment_requested.map((i) => `${i.quantity || ""} ${i.item}`.trim()).join(", ")}` : ""].filter(Boolean).join("\n") });
  const [mods, setMods] = useState([]);
  const [busy, setBusy] = useState(false);
  const [same, setSame] = useState(m.same_day);
  const [asked, setAsked] = useState([]);
  const [merge, setMerge] = useState(null);
  const [events, setEvents] = useState([]);
  useEffect(() => { api.get("/modules").then((r) => setMods(r.data.modules)); api.get("/events").then((r) => setEvents(r.data)); }, []);
  useEffect(() => { if (e.date) api.get("/inbound-requests/availability", { params: { day: e.date } }).then((r) => setSame(r.data)).catch(() => {}); }, [e.date]);
  const se = (k) => (ev) => setE({ ...e, [k]: ev.target.value });
  const low = (k) => (conf[k] < 0.7 ? warn : "");
  const create = async (target) => {
    if (target === "event" && !e.date) return toast.error("Indiquez la date de l'événement");
    if (!e.modules.length) return toast.error("Sélectionnez au moins un module");
    setBusy(true);
    const body = { target, asked, event: { ...e, title: e.title || "Nouvelle demande", guests: Number(e.guests) || 0, budget: Number(e.budget) || 0 },
      client: { ...c, contact_id: c.use }, organizer: o.name || o.company || o.use ? { ...o, contact_id: o.use, language: c.language } : null };
    try { const r = (await api.post(`/inbound-requests/${req.id}/convert`, body)).data; toast.success(`Demande créée${r.missing ? ` — ${r.missing} info(s) à demander` : ""}`); nav(r.url); } catch (err) { toast.error(errMsg(err)); }
    setBusy(false);
  };
  const openMerge = async (eid) => { try { const d = (await api.get(`/inbound-requests/${req.id}/diff/${eid}`)).data; setMerge({ eid, diffs: d, keys: d.map((i) => i.key) }); } catch (err) { toast.error(errMsg(err)); } };
  const doMerge = async () => { try { const r = (await api.post(`/inbound-requests/${req.id}/merge/${merge.eid}`, { keys: merge.keys })).data; toast.success("Événement mis à jour"); nav(r.url); } catch (err) { toast.error(errMsg(err)); } };
  const nf = (v) => (v ? "" : "bg-secondary");
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_2fr]">
      <details open className="card-soft h-fit p-5" data-testid="inbound-raw"><summary className="cursor-pointer text-sm font-semibold">Texte reçu · {SOURCES[req.source] || req.source} · {fmtDate(req.received_at)}</summary><p className="mt-3 whitespace-pre-wrap text-sm text-muted-foreground">{req.raw_text}</p></details>
      <div className="space-y-5">
        {!req.parsed && <div className="rounded-xl bg-amber-500/10 p-3 text-sm text-amber-700" data-testid="inbound-parse-failed">L'analyse automatique n'a rien pu extraire : remplissez le formulaire à la main.</div>}
        <Section title="Client" testid="inbound-client">
          {m.client && <div className="mb-3 rounded-xl border border-border p-3 text-sm" data-testid="inbound-client-match">Client existant : <b>{m.client.display_name}</b> — {m.client.events_count} événement(s)
            <div className="mt-2 flex gap-2"><Button size="sm" variant={c.use ? "default" : "outline"} onClick={() => setC({ ...c, use: m.client.id })} data-testid="inbound-client-use">Utiliser ce contact</Button><Button size="sm" variant={c.use ? "outline" : "default"} onClick={() => setC({ ...c, use: "" })} data-testid="inbound-client-new">Créer un nouveau contact</Button></div></div>}
          <div className="grid grid-cols-2 gap-3">
            <Input className={`${low("client_name")} ${nf(c.first_name)}`} placeholder="Prénom — non trouvé" value={c.first_name} onChange={(ev) => setC({ ...c, first_name: ev.target.value })} data-testid="inbound-first-name" />
            <Input className={`${low("client_name")} ${nf(c.last_name)}`} placeholder="Nom — non trouvé" value={c.last_name} onChange={(ev) => setC({ ...c, last_name: ev.target.value })} data-testid="inbound-last-name" />
            <Input className={nf(c.phone)} placeholder="Téléphone — non trouvé" value={c.phone} onChange={(ev) => setC({ ...c, phone: ev.target.value })} data-testid="inbound-phone" />
            <Input className={nf(c.email)} placeholder="E-mail — non trouvé" value={c.email} onChange={(ev) => setC({ ...c, email: ev.target.value })} data-testid="inbound-email" />
            <Input placeholder="Instagram" value={c.instagram_handle} onChange={(ev) => setC({ ...c, instagram_handle: ev.target.value })} data-testid="inbound-instagram" />
            <LanguageSelect value={c.language} onChange={(v) => setC({ ...c, language: v })} testid="inbound-language" />
          </div>
        </Section>
        {(o.name || o.company) && <Section title="Organisateur" testid="inbound-organizer">
          {m.organizer && <div className="mb-3 text-sm" data-testid="inbound-organizer-match"><label className="flex items-center gap-2"><input type="checkbox" checked={!!o.use} onChange={(ev) => setO({ ...o, use: ev.target.checked ? m.organizer.id : "" })} />Utiliser l'organisateur existant : <b>{m.organizer.display_name}</b></label></div>}
          {!o.use && <div className="grid grid-cols-2 gap-3"><Input placeholder="Nom" value={o.name} onChange={(ev) => setO({ ...o, name: ev.target.value })} data-testid="inbound-organizer-name" /><Input placeholder="Société" value={o.company} onChange={(ev) => setO({ ...o, company: ev.target.value })} data-testid="inbound-organizer-company" />
            <select className={sel} value={o.type || "wedding_planner"} onChange={(ev) => setO({ ...o, type: ev.target.value })} data-testid="inbound-organizer-type"><option value="wedding_planner">Wedding planner</option><option value="agence_evenementielle">Agence événementielle</option><option value="agence_communication">Agence de communication</option></select>
            <Input placeholder="E-mail" value={o.email} onChange={(ev) => setO({ ...o, email: ev.target.value })} /></div>}
        </Section>}
        <Section title="Événement" testid="inbound-event">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Titre" className="col-span-2"><Input value={e.title} onChange={se("title")} data-testid="inbound-title" /></Field>
            <Field label="Type"><select className={`${sel} ${low("category")}`} value={e.type} onChange={se("type")} data-testid="inbound-type">{EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
            <Field label={`Date${conf.date < 0.7 || x.event.date_is_approximate ? ` — à vérifier${x.event.date_raw ? ` (« ${x.event.date_raw} »)` : ""}` : ""}`}><Input type="date" className={conf.date < 0.7 || x.event.date_is_approximate ? warn : nf(e.date)} value={e.date} onChange={se("date")} data-testid="inbound-date" /></Field>
            <Field label="Début"><Input type="time" value={e.start_time} onChange={se("start_time")} /></Field><Field label="Fin"><Input type="time" value={e.end_time} onChange={se("end_time")} /></Field>
            <Field label="Invités"><Input type="number" className={`${low("guests")} ${nf(e.guests)}`} value={e.guests} onChange={se("guests")} data-testid="inbound-guests" /></Field>
            <Field label="Budget (€)"><div className="flex gap-2"><Input type="number" className={`${low("budget")} ${nf(e.budget)}`} value={e.budget} onChange={se("budget")} data-testid="inbound-budget" /><select className={`${sel} w-24`} value={e.budget_tax_mode} onChange={se("budget_tax_mode")}><option value="ttc">TTC</option><option value="ht">HT</option></select></div></Field>
            {m.venue && <label className="col-span-2 flex items-center gap-2 text-sm" data-testid="inbound-venue-match"><input type="checkbox" checked={!!e.venue_id} onChange={(ev) => setE({ ...e, venue_id: ev.target.checked ? m.venue.id : "" })} />Lieu existant : <b>{m.venue.name}</b> ({m.venue.zip} {m.venue.city})</label>}
            {!e.venue_id && (<><Field label="Lieu"><Input className={`${low("venue")} ${nf(e.venue_name)}`} placeholder="non trouvé" value={e.venue_name} onChange={se("venue_name")} data-testid="inbound-venue-name" /></Field><Field label="Ville"><Input value={e.venue_city} onChange={se("venue_city")} data-testid="inbound-venue-city" /></Field>
              <Field label="Adresse"><Input value={e.venue_address} onChange={se("venue_address")} /></Field><Field label="Code postal"><Input value={e.venue_zip} onChange={se("venue_zip")} data-testid="inbound-venue-zip" /></Field></>)}
            <div className="col-span-2 flex flex-wrap gap-2" data-testid="inbound-modules">{mods.map((mo) => { const on = e.modules.includes(mo.key); return <button key={mo.key} type="button" aria-pressed={on} onClick={() => setE({ ...e, modules: on ? e.modules.filter((k) => k !== mo.key) : [...e.modules, mo.key] })} data-testid={`inbound-module-${mo.key}`} className={`h-9 rounded-full border px-4 text-sm font-medium ${on ? "border-primary bg-primary text-white" : "border-border"}`}>{mo.label}</button>; })}</div>
            <Field label="Notes internes" className="col-span-2"><Textarea rows={3} value={e.notes} onChange={se("notes")} data-testid="inbound-notes" /></Field>
          </div>
          {e.date && (same.length ? <div className="mt-3 rounded-xl bg-amber-500/10 p-3 text-sm text-amber-700" data-testid="inbound-busy">Déjà {same.length} événement(s) le {fmtDate(e.date)} : {same.map((s) => <Link key={s.id} to={`/evenements/${s.id}`} className="underline">{s.title} </Link>)}</div>
            : <div className="mt-3 rounded-xl bg-emerald-500/10 p-3 text-sm text-emerald-700" data-testid="inbound-free">Libre ce jour-là</div>)}
        </Section>
        {x.questions_to_ask.length > 0 && <Section title="À demander au client" testid="inbound-questions">
          {x.questions_to_ask.map((q) => <label key={q} className="flex items-start gap-2 py-1 text-sm"><input type="checkbox" className="mt-1" checked={asked.includes(q)} onChange={() => setAsked(asked.includes(q) ? asked.filter((a) => a !== q) : [...asked, q])} />{q}</label>)}
          {x.followup_message && <Button size="sm" variant="outline" className="mt-2" onClick={() => navigator.clipboard.writeText(x.followup_message).then(() => toast.success("Message copié"))} data-testid="inbound-copy-followup">Copier un message de relance</Button>}
        </Section>}
        {merge && <Section title="Différences à appliquer" testid="inbound-merge">
          {!merge.diffs.length && <p className="text-sm text-muted-foreground">Aucune différence détectée : le texte sera seulement ajouté à l'historique.</p>}
          {merge.diffs.map((d) => <label key={d.key} className="flex items-center gap-2 py-1 text-sm" data-testid={`inbound-diff-${d.key}`}><input type="checkbox" checked={merge.keys.includes(d.key)} onChange={() => setMerge({ ...merge, keys: merge.keys.includes(d.key) ? merge.keys.filter((k) => k !== d.key) : [...merge.keys, d.key] })} />{d.label} : {String(d.old)} → <b>{String(d.new)}</b></label>)}
          <Button className="mt-3" onClick={doMerge} data-testid="inbound-merge-apply">Valider et ajouter à l'historique</Button>
        </Section>}
        <div className="flex flex-wrap items-center gap-2">
          {can("crm:manage") && <Button disabled={busy} onClick={() => create("opportunity")} data-testid="inbound-create-opportunity">{busy ? "Création…" : "Créer le client et l'opportunité"}</Button>}
          <Button variant={can("crm:manage") ? "outline" : "default"} disabled={busy} onClick={() => create("event")} data-testid="inbound-create">Créer directement l'événement</Button>
          {c.use && <Link className="text-sm font-semibold underline" to={`/devis-factures?new=1&client=${c.use}`} data-testid="inbound-create-quote">Créer directement un devis</Link>}
          <select className={`${sel} w-auto`} value="" onChange={(ev) => ev.target.value && openMerge(ev.target.value)} data-testid="inbound-merge-select"><option value="">Ajouter à un événement existant…</option>{events.filter((v) => !m.client || v.client_id === m.client.id).concat(events.filter((v) => m.client && v.client_id !== m.client.id)).map((v) => <option key={v.id} value={v.id}>{v.code} · {v.title}</option>)}</select>
          <Button variant="ghost" onClick={() => { toast.success("Brouillon enregistré"); nav("/demandes"); }} data-testid="inbound-save-draft">Enregistrer comme brouillon</Button>
        </div>
      </div>
    </div>
  );
}

export default function DemandeNouvelle() {
  const [sp] = useSearchParams();
  const [req, setReq] = useState(null);
  useEffect(() => { if (sp.get("id")) api.get(`/inbound-requests/${sp.get("id")}`).then((r) => setReq(r.data)).catch((e) => toast.error(errMsg(e))); }, [sp]);
  return (<div><PageHeader title="Coller une demande" subtitle="Collez le message reçu : l'IA pré-remplit le client et l'événement, vous vérifiez, puis vous créez." />{req ? <Review req={req} /> : <Paste onParsed={setReq} />}</div>);
}

const BADGE = { sms: "SMS", instagram: "Instagram", whatsapp: "WhatsApp", email: "Email", telephone: "Téléphone", autre: "Autre" };
export function Demandes() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/inbound-requests").then((r) => setRows(r.data)); }, []);
  return (
    <div><PageHeader title="Demandes" subtitle="Événements au statut Demande et brouillons, par date de réception." actions={<Link to="/demande/nouvelle"><Button data-testid="demandes-new"><ClipboardPaste />Coller une demande</Button></Link>} />
      <div className="card-soft divide-y divide-border" data-testid="demandes-list">
        {rows && !rows.length && <p className="p-6 text-sm text-muted-foreground">Aucune demande en attente.</p>}
        {(rows || []).map((r) => <Link key={r.id} to={r.event_id ? `/evenements/${r.event_id}` : `/demande/nouvelle?id=${r.id}`} className="flex flex-wrap items-center gap-3 p-4 hover:bg-secondary" data-testid={`demande-row-${r.id}`}>
          <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold">{BADGE[r.source]}</span><span className="min-w-0 flex-1 truncate font-medium">{r.title}</span>
          {r.status === "draft" && <span className="rounded-full bg-amber-500/10 px-2.5 py-0.5 text-xs font-semibold text-amber-700">Brouillon</span>}
          {r.missing > 0 && <span className="rounded-full bg-red-500/10 px-2.5 py-0.5 text-xs font-semibold text-red-600">{r.missing} info(s) manquante(s)</span>}
          <span className="text-xs text-muted-foreground">reçu le {fmtDate(r.received_at)}{r.event_date ? ` · événement le ${fmtDate(r.event_date)}` : ""}</span></Link>)}
      </div></div>
  );
}
