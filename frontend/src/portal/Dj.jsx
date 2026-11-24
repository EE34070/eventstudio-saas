import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";

const ko = (e) => toast.error(errMsg(e));
export const DJ_COLORS = { available: "bg-emerald-500 text-white", available_default: "bg-emerald-200", unavailable: "bg-zinc-400 text-white", external_busy: "bg-zinc-400 text-white", maybe: "bg-orange-400 text-white", option: "bg-blue-500 text-white", confirmed: "bg-violet-600 text-white", unknown: "bg-secondary" };
const btn = "rounded-full border border-border px-3 py-2 text-sm font-medium";
const inp = "h-10 rounded-xl border border-border bg-background px-3 text-sm";
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function Calendar({ L }) {
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const [d, setD] = useState(null);
  const [sel, setSel] = useState([]);
  const [q, setQ] = useState({ weekday: 5, start: "", end: "" });
  const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  const load = useCallback(() => api.get("/portal/provider/dj/availability", { params: { start: iso(month), end: iso(last) } }).then((r) => setD(r.data)).catch(() => setD(false)), [month]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  if (d === false) return null;
  const by = Object.fromEntries((d?.days || []).map((x) => [x.date, x]));
  const put = (body) => api.put("/portal/provider/dj/availability", body).then((r) => { toast.success(`${r.data.updated} ${L("jour(s) mis à jour", "day(s) updated")}`); setSel([]); load(); }).catch(ko);
  const days = Array.from({ length: last.getDate() }, (_, i) => new Date(month.getFullYear(), month.getMonth(), i + 1));
  const states = [["available", L("Disponible", "Available")], ["unavailable", L("Indisponible", "Unavailable")], ["maybe", L("À confirmer", "To confirm")], ["external_busy", L("Occupé (privé)", "Busy (private)")], ["clear", L("Effacer", "Clear")]];
  return (
    <div className="space-y-4" data-testid="dj-calendar">
      <div className="flex items-center justify-between"><button className={btn} onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} data-testid="dj-cal-prev">‹</button>
        <b data-testid="dj-cal-month">{month.toLocaleDateString(L("fr-FR", "en-GB"), { month: "long", year: "numeric" })}</b>
        <button className={btn} onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} data-testid="dj-cal-next">›</button></div>
      <div className="grid grid-cols-7 gap-1 text-center text-sm">
        {Array.from({ length: (month.getDay() + 6) % 7 }, (_, i) => <span key={`e${i}`} />)}
        {days.map((x) => { const k = iso(x), a = by[k], lock = ["option", "confirmed"].includes(a?.state); return (
          <button key={k} disabled={lock} onClick={() => setSel(sel.includes(k) ? sel.filter((s) => s !== k) : [...sel, k])} className={`h-11 rounded-lg ${DJ_COLORS[a?.state || "unknown"]} ${sel.includes(k) ? "ring-2 ring-foreground" : ""}`} data-testid={`dj-day-${k}`}>{x.getDate()}</button>); })}
      </div>
      {sel.length > 0 && <div className="flex flex-wrap gap-2" data-testid="dj-cal-actions">{states.map(([s, l]) => <button key={s} className={btn} onClick={() => put({ dates: sel, state: s })} data-testid={`dj-set-${s}`}>{l}</button>)}</div>}
      <div className="space-y-2 rounded-2xl border border-border p-3 text-sm"><b>{L("Saisie rapide", "Quick fill")}</b>
        <div className="flex flex-wrap items-center gap-2">
          <select className={inp} value={q.weekday} onChange={(e) => setQ({ ...q, weekday: Number(e.target.value) })} data-testid="dj-quick-weekday">{[L("Lundis", "Mondays"), L("Mardis", "Tuesdays"), L("Mercredis", "Wednesdays"), L("Jeudis", "Thursdays"), L("Vendredis", "Fridays"), L("Samedis", "Saturdays"), L("Dimanches", "Sundays")].map((n, i) => <option key={n} value={i}>{n}</option>)}</select>
          <input type="date" className={inp} value={q.start} onChange={(e) => setQ({ ...q, start: e.target.value })} data-testid="dj-quick-start" /><input type="date" className={inp} value={q.end} onChange={(e) => setQ({ ...q, end: e.target.value })} data-testid="dj-quick-end" />
          {states.slice(0, 2).map(([s, l]) => <button key={s} className={btn} disabled={!q.start || !q.end} onClick={() => put({ ...q, state: s })} data-testid={`dj-quick-${s}`}>→ {l}</button>)}
        </div>
        <label className="flex items-center gap-2">{L("Jours non renseignés :", "Days left blank:")}<select className={inp} value={d?.meta?.default_state || "unknown"} onChange={(e) => put({ dates: [], state: "clear", default_state: e.target.value })} data-testid="dj-default-state"><option value="unknown">{L("Inconnus", "Unknown")}</option><option value="available">{L("Disponibles", "Available")}</option></select></label>
        <p className="text-xs text-muted-foreground" data-testid="dj-cal-updated">{L("Calendrier mis à jour le", "Calendar updated on")} {d?.meta?.last_updated_at?.slice(0, 10) || "—"}</p></div>
    </div>
  );
}

const STATUS = { option_requested: ["Option demandée", "Hold requested"], option_accepted: ["Option acceptée", "Hold accepted"], option_refused: ["Refusée", "Declined"], option_conditions: ["Sous conditions", "Conditional"], confirmed: ["Confirmée", "Confirmed"], acknowledged: ["Accusé reçu", "Acknowledged"], done: ["Réalisée", "Done"], invoiced: ["Facturée", "Invoiced"], paid: ["Payée", "Paid"], cancelled: ["Annulée", "Cancelled"], option_lifted: ["Option levée", "Hold released"], availability_requested: ["Disponibilité demandée", "Availability requested"], available: ["Disponible", "Available"], not_available: ["Pas disponible", "Not available"] };

function Bookings({ L }) {
  const [d, setD] = useState(null);
  const load = useCallback(() => api.get("/portal/provider/dj/home").then((r) => setD(r.data)).catch(() => setD(false)), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const reply = (b, r) => { const comment = r === "accept" ? "" : window.prompt(L("Commentaire", "Comment")) ?? null; if (comment !== null) api.post(`/portal/provider/dj/bookings/${b.id}/reply`, { reply: r, comment }).then((x) => { if (x.data.warning) toast.warning(L(x.data.warning, "You already have a booking in this time slot")); load(); }).catch(ko); };
  const deposit = (b, file) => { const fd = new FormData(); fd.append("booking_ids", b.id); fd.append("file", file); api.post("/portal/provider/dj/invoices", fd).then((r) => { toast[r.data.match_status === "conform" ? "success" : "warning"](r.data.match_status === "conform" ? L("Facture conforme", "Invoice OK") : r.data.mismatch_reasons.join(" ; ")); load(); }).catch(ko); };
  return (
    <div className="space-y-3" data-testid="dj-bookings">
      {d.bookings.length === 0 && <p className="text-sm text-muted-foreground">{L("Aucune option ni mission.", "No holds or jobs.")}</p>}
      {d.bookings.map((b) => (
        <div key={b.id} className="space-y-2 rounded-2xl border border-border p-3 text-sm" data-testid={`dj-booking-${b.id}`}>
          <div className="flex flex-wrap justify-between gap-2"><b>{b.date} · {b.start_time}–{b.end_time} · {b.city}</b><span className="rounded-full bg-secondary px-2 py-0.5 text-xs" data-testid={`dj-booking-status-${b.id}`}>{L(...(STATUS[b.status] || [b.status, b.status]))}</span></div>
          <div>{b.event_type} · {b.proposed_fee} € {b.fee_tax_mode?.toUpperCase()}{b.travel_fee ? ` + ${b.travel_fee} €` : ""}</div>
          {b.conflict && <div className="rounded-lg bg-amber-500/15 p-2 text-xs font-semibold text-amber-700" data-testid={`dj-booking-conflict-${b.id}`}>{L("Vous avez déjà une prestation à ce créneau", "You already have a booking in this time slot")}</div>}
          {b.address && <div data-testid={`dj-booking-address-${b.id}`}>{b.venue_name} — {b.address}<br />{b.access}</div>}
          {["option_requested", "option_conditions"].includes(b.status) && <div className="flex flex-wrap gap-2"><span className="w-full text-xs text-muted-foreground">{L("Réponse attendue avant le", "Reply before")} {b.option_expires_at}</span>
            <button className={`${btn} bg-foreground text-background`} onClick={() => reply(b, "accept")} data-testid={`dj-accept-${b.id}`}>{L("Accepter", "Accept")}</button><button className={btn} onClick={() => reply(b, "refuse")} data-testid={`dj-refuse-${b.id}`}>{L("Refuser", "Decline")}</button><button className={btn} onClick={() => reply(b, "conditions")} data-testid={`dj-conditions-${b.id}`}>{L("Sous conditions", "With conditions")}</button></div>}
          {b.status === "availability_requested" && <div className="flex flex-wrap gap-2"><span className="w-full text-xs text-muted-foreground">{L("Êtes-vous disponible à cette date ? (simple question, sans engagement)", "Are you available on this date? (no commitment)")}</span>
            {[[true, L("Oui, disponible", "Yes, available")], [false, L("Non", "No")]].map(([v, l]) => <button key={l} className={`${btn} ${v ? "bg-foreground text-background" : ""}`} onClick={() => api.post(`/portal/provider/dj/bookings/${b.id}/availability`, { available: v }).then(load).catch(ko)} data-testid={`dj-avail-${v ? "yes" : "no"}-${b.id}`}>{l}</button>)}</div>}
          {b.status === "confirmed" && <button className={`${btn} bg-foreground text-background`} onClick={() => api.post(`/portal/provider/dj/bookings/${b.id}/ack`).then(load).catch(ko)} data-testid={`dj-ack-${b.id}`}>{L("J'accuse réception", "Acknowledge")}</button>}
          {b.status === "done" && <label className={`${btn} inline-block cursor-pointer`} data-testid={`dj-invoice-${b.id}`}>{L("Déposer ma facture", "Upload my invoice")}<input type="file" accept="application/pdf,image/*" className="hidden" onChange={(e) => e.target.files[0] && deposit(b, e.target.files[0])} /></label>}
        </div>))}
      {d.invoices.length > 0 && <div className="rounded-2xl border border-border p-3 text-sm" data-testid="dj-my-invoices"><b>{L("Mes factures", "My invoices")}</b>{d.invoices.filter((i) => !i.superseded).map((i) => <div key={i.id}>{i.number || "—"} · {i.total_ht} € · {i.status}{i.refuse_reason ? ` — ${i.refuse_reason}` : ""}</div>)}</div>}
    </div>
  );
}

function Profile({ L }) {
  const [f, setF] = useState(null);
  useEffect(() => { api.get("/portal/provider/dj/profile").then((r) => setF(r.data)).catch(() => setF(false)); }, []);
  if (!f) return null;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const pair = (list, a, b) => list.map((x) => `${x[a]}:${x[b]}`).join(", ");
  const parse = (s, a, b, num) => s.split(",").map((x) => x.trim().split(":")).filter((x) => x[0] && x[1]).map((x) => ({ [a]: x[0].trim(), [b]: num ? Number(x[1]) : x[1].trim() }));
  const save = () => api.put("/portal/provider/dj/profile", { ...f, media_links: (f.links ?? f.media_links.join("\n")).split("\n").filter(Boolean), mc_languages: parse(f.langs ?? pair(f.mc_languages, "lang", "level"), "lang", "level"), genres: parse(f.gen ?? pair(f.genres, "key", "level"), "key", "level", true) }).then(() => toast.success(L("Profil enregistré", "Profile saved"))).catch(ko);
  return (
    <div className="space-y-2 text-sm" data-testid="dj-profile">
      <input className={`${inp} w-full`} placeholder={L("Nom de scène", "Stage name")} value={f.stage_name} onChange={set("stage_name")} data-testid="dj-profile-stage-name" />
      <textarea className="w-full rounded-xl border border-border bg-background p-3" rows={3} placeholder="Bio (français)" value={f.bio_fr} onChange={set("bio_fr")} data-testid="dj-profile-bio-fr" />
      <textarea className="w-full rounded-xl border border-border bg-background p-3" rows={3} placeholder="Bio (English)" value={f.bio_en} onChange={set("bio_en")} data-testid="dj-profile-bio-en" />
      <label className="block">{L("Langues au micro (ex. fr:fluent, en:correct, es:basic)", "MC languages (e.g. fr:fluent, en:correct)")}<input className={`${inp} w-full`} value={f.langs ?? pair(f.mc_languages, "lang", "level")} onChange={set("langs")} data-testid="dj-profile-languages" /></label>
      <label className="block">{L("Styles, niveau 1 à 3 (ex. pop:3, 2000s:2) — ", "Genres, level 1–3 — ")}{Object.keys(f.genre_list).join(", ")}<input className={`${inp} w-full`} value={f.gen ?? pair(f.genres, "key", "level")} onChange={set("gen")} data-testid="dj-profile-genres" /></label>
      <label className="block">{L("Liens mixes / vidéos (un par ligne)", "Mix / video links (one per line)")}<textarea className="w-full rounded-xl border border-border bg-background p-3" rows={2} value={f.links ?? f.media_links.join("\n")} onChange={set("links")} data-testid="dj-profile-links" /></label>
      <button className={`${btn} bg-foreground text-background`} onClick={save} data-testid="dj-profile-save">{L("Enregistrer", "Save")}</button>
    </div>
  );
}

export function DjSpace({ tr }) {
  const L = (fr, en) => (tr.en ? en : fr);
  const [tab, setTab] = useState("bookings");
  const tabs = [["bookings", L("Options & missions", "Holds & jobs")], ["calendar", L("Disponibilités", "Availability")], ["profile", L("Profil DJ", "DJ profile")]];
  return (
    <div className="space-y-4" data-testid="dj-space">
      <div className="flex gap-2 overflow-x-auto">{tabs.map(([k, l]) => <button key={k} className={`${btn} ${tab === k ? "bg-foreground text-background" : ""}`} onClick={() => setTab(k)} data-testid={`dj-tab-${k}`}>{l}</button>)}</div>
      {tab === "bookings" ? <Bookings L={L} /> : tab === "calendar" ? <Calendar L={L} /> : <Profile L={L} />}
    </div>
  );
}

export function ClientDj({ eid, en }) {
  const [d, setD] = useState(null);
  const load = useCallback(() => api.get(`/portal/client/events/${eid}/dj`).then((r) => setD(r.data)).catch(() => setD(null)), [eid]);
  useEffect(() => { load(); }, [load]);
  if (!d?.djs?.length && !d?.confirmed?.length) return null;
  return (
    <div className="mt-6 space-y-3" data-testid="client-dj"><h2 className="text-lg font-bold">{en ? "Your DJ" : "Votre DJ"}</h2>
      {d.confirmed?.length > 0 && <p className="rounded-2xl border border-border p-3 text-sm" data-testid="client-dj-confirmed">{en ? "Your confirmed DJ: " : "Votre DJ confirmé : "}<b>{d.confirmed.join(", ")}</b></p>}
      {d.djs.map((x) => (
        <div key={x.id} className="flex gap-3 rounded-2xl border border-border p-3 text-sm" data-testid={`client-dj-${x.id}`}>
          {x.photo_url && <img src={x.photo_url} alt={x.stage_name} className="h-20 w-20 rounded-xl object-cover" />}
          <div className="flex-1 space-y-1"><b>{x.stage_name}</b><p className="whitespace-pre-line">{x.bio}</p><p className="text-xs text-muted-foreground">{x.languages.join(" · ").toUpperCase()}</p>
            {x.media_links.map((l) => <a key={l} href={l} target="_blank" rel="noreferrer" className="block truncate text-xs underline">{l}</a>)}
            <button className={`${btn} ${d.preferred_id === x.id ? "bg-foreground text-background" : ""}`} onClick={() => api.post(`/portal/client/events/${eid}/dj/preference`, { provider_id: x.id }).then(load).catch(ko)} data-testid={`client-dj-prefer-${x.id}`}>{d.preferred_id === x.id ? (en ? "My preference" : "Ma préférence") : (en ? "I prefer this DJ" : "Je préfère ce DJ")}</button></div>
        </div>))}
    </div>
  );
}
