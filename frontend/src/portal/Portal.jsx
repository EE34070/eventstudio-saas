import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useClerk } from "@clerk/react";
import { toast } from "sonner";
import { Home, Music, FileText, Receipt, Clock, MessageCircle, Users, User, Briefcase, CalendarDays, MapPin, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import MusicPlan from "@/portal/Music";
import { makeT } from "@/portal/tr";
import { MySocial } from "@/pages/MonEspace";
import { StaffHome, Positions, Agenda, Space } from "@/portal/Staff";
import { DjSpace, ClientDj } from "@/portal/Dj";
import CoupleSpace, { loadWedding } from "@/wedding/CoupleSpace";

const ICON = { Home, Music, FileText, Receipt, Clock, MessageCircle, Users };
const P = createContext(null);
const useP = () => useContext(P);
const card = "rounded-3xl border border-border bg-card p-5";
const openUrl = (u) => window.open(u.startsWith("/api") ? process.env.REACT_APP_BACKEND_URL + u : u, "_blank", "noopener");

const Empty = ({ title, text }) => <div className={`${card} text-center text-sm text-muted-foreground`} data-testid="portal-empty">{title && <div className="mb-1 text-base font-semibold text-foreground">{title}</div>}{text}</div>;
const Badge = ({ children, ok }) => <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${ok ? "bg-emerald-500/10 text-emerald-700" : "bg-secondary"}`}>{children}</span>;

function useLoad(path, deps = []) {
  const { t } = useP();
  const [d, setD] = useState(null);
  const load = useCallback(() => api.get(path).then((r) => setD(r.data)).catch(() => toast.error(t("error"))), [path, t]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setD(null); load(); }, [load, ...deps]);
  return [d, load, setD];
}

function Thread({ rows, onSend, disabled }) {
  const { t, date } = useP();
  const [body, setBody] = useState("");
  return (
    <div className={card} data-testid="portal-thread">
      {!rows.length && <p className="text-sm text-muted-foreground">{t("messages_empty")}</p>}
      {rows.map((m) => <div key={m.id} className={`mb-2 max-w-[85%] rounded-2xl px-3 py-2 text-sm ${m.from_role === "staff" ? "bg-secondary" : "ml-auto bg-primary text-white"}`}><div className="whitespace-pre-wrap">{m.body}</div><div className="mt-0.5 text-[11px] opacity-70">{m.from_name} · {date(m.at, { day: "numeric", month: "short" })}</div></div>)}
      {!disabled && <div className="mt-3 flex gap-2"><Textarea rows={2} value={body} placeholder={t("message_placeholder")} onChange={(e) => setBody(e.target.value)} data-testid="portal-message-input" /><Button disabled={!body.trim()} onClick={() => onSend(body).then(() => setBody(""))} data-testid="portal-message-send">{t("send")}</Button></div>}
    </div>
  );
}

function Upload({ label, onRef, testid }) {
  const { t } = useP();
  const ref = useRef(null);
  const pick = async (e) => { const fd = new FormData(); fd.append("file", e.target.files[0]); e.target.value = ""; try { onRef((await api.post("/portal/files", fd)).data.ref); } catch { toast.error(t("error")); } };
  return <><input ref={ref} type="file" hidden accept="application/pdf" onChange={pick} data-testid={`${testid}-input`} /><Button size="sm" variant="outline" onClick={() => ref.current.click()} data-testid={testid}>{label}</Button></>;
}

// ---------- Client ----------
function ClientHome({ ev }) {
  const { t, date, money } = useP();
  const days = ev.start ? Math.ceil((new Date(ev.start.slice(0, 10)) - new Date(new Date().toISOString().slice(0, 10))) / 86400000) : null;
  const v = ev.venue;
  return (
    <div className="space-y-4" data-testid="client-home">
      <div className="rounded-3xl bg-foreground p-6 text-background"><div className="text-xs uppercase tracking-widest opacity-70">{ev.type}</div><h1 className="mt-1 text-3xl font-bold" data-testid="client-event-title">{ev.title}</h1>
        <div className="mt-2 text-sm opacity-80">{ev.date_tbc ? t("date_tbc") : date(ev.start)}{ev.guests ? ` · ${t("guests", { n: ev.guests })}` : ""}</div>
        {!ev.date_tbc && days != null && <div className="mt-4 text-4xl font-bold" data-testid="client-countdown">{days > 0 ? t("countdown_days", { n: days }) : days === 0 ? t("countdown_today") : t("countdown_past")}</div>}</div>
      {ev.read_only && <div className="rounded-2xl bg-amber-500/10 p-3 text-sm text-amber-700">{t("read_only")}</div>}
      {v && <div className={card}><div className="eyebrow">{t("venue")}</div><div className="font-semibold">{v.name}</div><div className="text-sm text-muted-foreground">{[v.address, v.zip, v.city].filter(Boolean).join(" ")}</div>
        {v.access_instructions && <p className="mt-2 text-sm"><b>{t("access")} :</b> {v.access_instructions}</p>}
        <a className="mt-2 inline-flex items-center gap-1 text-sm font-semibold underline" target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/search?query=${encodeURIComponent([v.address, v.zip, v.city].filter(Boolean).join(" "))}`}><MapPin className="h-4 w-4" />{t("map")}</a></div>}
      {ev.progress.length > 0 && <div className={card}><div className="eyebrow mb-2">{t("progress")}</div>{ev.progress.map((p) => <div key={p.key} className="flex items-center gap-2 py-1 text-sm"><span className={`flex h-5 w-5 items-center justify-center rounded-full ${p.done ? "bg-emerald-500 text-white" : "border border-border"}`}>{p.done && <Check className="h-3 w-3" />}</span>{t(`progress_${p.key}`)}</div>)}</div>}
      <div className={card}><div className="eyebrow mb-2">{t("deadlines")}</div>{!ev.deadlines.length && <p className="text-sm text-muted-foreground">{t("no_deadline")}</p>}
        {ev.deadlines.map((d, i) => <div key={i} className="flex justify-between py-1 text-sm"><span>{d.kind === "music" ? t("deadline_music") : t("deadline_balance", { amount: money(d.amount) })}</span><b>{date(d.date, { day: "numeric", month: "short", year: "numeric" })}</b></div>)}</div>
      <div className={card}><div className="eyebrow">{t("your_contact")}</div><div className="font-semibold">{ev.contact.name}</div><div className="text-sm text-muted-foreground">{[ev.contact.phone, ev.contact.email].filter(Boolean).join(" · ")}</div></div>
    </div>
  );
}

function ClientDocs({ eid }) {
  const { t, date, en } = useP();
  const [rows] = useLoad(`/portal/client/events/${eid}/documents`);
  if (!rows) return null;
  if (!rows.length) return <Empty text={t("docs_empty")} />;
  return <div className={`${card} divide-y divide-border`} data-testid="client-documents">{rows.map((d) => <div key={d.id} className="flex items-center gap-3 py-3 text-sm"><FileText className="h-5 w-5 shrink-0" /><div className="min-w-0 flex-1"><div className="truncate font-medium">{(en && d.title_en) || d.title}</div><div className="text-xs text-muted-foreground">{date(d.date, { day: "numeric", month: "short", year: "numeric" })}</div></div>
    <Button size="sm" variant="outline" onClick={() => api.get(`/portal/client/events/${eid}/documents/${d.id}/link`).then((r) => openUrl(r.data.url)).catch(() => toast.error(t("error")))} data-testid={`client-doc-${d.id}`}>{t("download")}</Button></div>)}</div>;
}

function ClientBilling({ eid }) {
  const { t, date, money } = useP();
  const [b] = useLoad(`/portal/client/events/${eid}/billing`);
  if (!b) return null;
  if (!b.quotes.length && !b.invoices.length) return <Empty text={t("billing_empty")} />;
  return (
    <div className="space-y-4" data-testid="client-billing">
      {b.quotes.length > 0 && <div className={card}><div className="eyebrow mb-2">{t("quotes")}</div>{b.quotes.map((q) => <div key={q.id} className="flex flex-wrap items-center gap-2 py-2 text-sm"><b>{q.number}</b><Badge ok={q.status === "accepte"}>{t(`q_${q.status}`)}</Badge><span className="flex-1 text-right">{t("total_ttc", { amount: money(q.total_ttc) })}</span>
        <Link className="font-semibold underline" to={q.url} target="_blank" data-testid={`client-quote-${q.number}`}>{q.status === "envoye" ? t("view_sign") : t("view")}</Link></div>)}</div>}
      {b.invoices.length > 0 && <div className={card}><div className="eyebrow mb-2">{t("invoices")}</div>{b.invoices.map((i) => <div key={i.id} className="py-2 text-sm"><div className="flex flex-wrap items-center gap-2"><b>{i.number}</b><span className="text-muted-foreground">{t(`kind_${i.kind}`)}</span><Badge ok={i.status === "payee"}>{t(`i_${i.status}`)}</Badge><span className="flex-1 text-right">{t("total_ttc", { amount: money(i.total_ttc) })}</span>
        <button className="font-semibold underline" onClick={() => openUrl(i.pdf)}>{t("pdf")}</button></div>{i.balance_due > 0 && <div className="text-xs text-muted-foreground">{t("balance_due", { amount: money(i.balance_due) })} · {t("due_on", { date: date(i.due_date, { day: "numeric", month: "short", year: "numeric" }) })}</div>}</div>)}</div>}
    </div>
  );
}

function Items({ items }) {
  const { en } = useP();
  return items.map((i) => <div key={i.id} className="flex gap-3 py-2 text-sm"><b className="w-12 shrink-0">{i.time}</b><div><div className="font-medium">{(en && i.label_en) || i.label}</div><div className="text-muted-foreground">{(en && i.description_en) || i.description}</div></div></div>);
}

function ClientTimeline({ eid, ro }) {
  const { t } = useP();
  const [d, , setD] = useLoad(`/portal/client/events/${eid}/timeline`);
  const [c, setC] = useState("");
  if (!d) return null;
  return (
    <div className="space-y-4" data-testid="client-timeline">
      {d.items.length ? <div className={`${card} divide-y divide-border`}><Items items={d.items} /></div> : <Empty text={t("timeline_empty")} />}
      <div className={card}><div className="eyebrow mb-2">{t("comments")}</div>{d.comments.map((x) => <div key={x.id} className="border-b border-border py-2 text-sm last:border-0">{x.body}<div className="text-xs text-muted-foreground">{x.by}</div></div>)}
        {!ro && <div className="mt-2 flex gap-2"><Input value={c} placeholder={t("comment_placeholder")} onChange={(e) => setC(e.target.value)} data-testid="client-comment-input" /><Button disabled={!c.trim()} onClick={() => api.post(`/portal/client/events/${eid}/timeline/comments`, { body: c }).then((r) => { setD(r.data); setC(""); }).catch(() => toast.error(t("error")))} data-testid="client-comment-add">{t("comment_add")}</Button></div>}</div>
    </div>
  );
}

function ClientMessages({ eid, ro }) {
  const [rows, , setRows] = useLoad(`/portal/client/events/${eid}/messages`);
  return rows && <Thread rows={rows} disabled={ro} onSend={(body) => api.post(`/portal/client/events/${eid}/messages`, { body }).then((r) => setRows(r.data))} />;
}

function Client() {
  const tr = useP();
  const { t, en, setTabs, tab, setTab } = tr;
  const [events] = useLoad("/portal/client/events");
  const [eid, setEid] = useState("");
  const [ev, setEv] = useState(null);
  useEffect(() => { if (events?.length && !eid) setEid(events[0].id); }, [events, eid]);
  useEffect(() => { if (eid) api.get(`/portal/client/events/${eid}`).then((r) => { setEv(r.data); setTabs(r.data.modules.map((m) => ({ key: m.key, label: m.key === "home" ? t("tab_home") : (en && m.label_en) || m.label, icon: ICON[m.icon] || FileText }))); }).catch(() => toast.error(t("error"))); }, [eid, en, setTabs, t]);
  if (!events) return null;
  if (!events.length) return <Empty title={t("no_event_title")} text={t("no_event_text")} />;
  if (!ev) return null;
  const mod = ev.modules.find((m) => m.key === tab);
  const ro = ev.read_only || !mod?.editable;
  return (
    <>
      {events.length > 1 && <select className="mb-4 h-10 w-full rounded-full border border-border bg-card px-4 text-sm" value={eid} onChange={(e) => { setEid(e.target.value); setTab("home"); }} data-testid="client-event-select">{events.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}</select>}
      {tab === "home" || !mod ? <><ClientHome ev={ev} /><ClientDj eid={eid} en={en} /></> : !mod.built ? <Empty title={t("soon_title")} text={t("soon_text")} /> : tab === "music" ? <MusicPlan base={`/portal/client/events/${eid}/music`} tr={tr} /> : tab === "documents" ? <ClientDocs eid={eid} /> : tab === "billing" ? <ClientBilling eid={eid} /> : tab === "timeline" ? <ClientTimeline eid={eid} ro={ro} /> : <ClientMessages eid={eid} ro={ro} />}
    </>
  );
}

// ---------- Prestataire ----------
function Mission({ id, onBack }) {
  const tr = useP();
  const { t, date, money, preview } = tr;
  const [mu, setMu] = useState(false);
  const [m, load] = useLoad(`/portal/provider/missions/${id}`);
  if (!m) return null;
  const act = (p, body, msg) => api.post(`/portal/provider/missions/${id}/${p}`, body).then(() => { toast.success(msg); load(); }).catch(() => toast.error(t("error")));
  const v = m.venue;
  return (
    <div className="space-y-4" data-testid="provider-mission">
      <button className="text-sm font-semibold underline" onClick={onBack}>← {t("back")}</button>
      <div className="rounded-3xl bg-foreground p-6 text-background"><div className="text-xs uppercase tracking-widest opacity-70">{m.category} · {m.event_type}</div><h1 className="mt-1 text-2xl font-bold">{date(m.date)}</h1><div className="mt-1 text-sm opacity-80">{t("schedule")} : {m.start_time} – {m.end_time}</div><div className="mt-3"><Badge>{t(`s_${m.status}`)}</Badge></div></div>
      <div className={card}><div className="eyebrow">{t("venue")}</div><div className="font-semibold">{v.name}</div><div className="text-sm text-muted-foreground">{[v.address, v.zip, v.city].filter(Boolean).join(" ")}</div>{v.access_instructions && <p className="mt-2 text-sm"><b>{t("access")} :</b> {v.access_instructions}</p>}
        <a className="mt-2 inline-flex items-center gap-1 text-sm font-semibold underline" target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/search?query=${encodeURIComponent([v.address, v.zip, v.city].filter(Boolean).join(" "))}`}><MapPin className="h-4 w-4" />{t("map")}</a></div>
      <div className={card}><div className="eyebrow">{t("onsite")}</div>{m.onsite_contacts.length ? m.onsite_contacts.map((c, i) => <div key={i} className="text-sm"><b>{c.name}</b> {c.role} · {c.phone}</div>) : <p className="text-sm text-muted-foreground">{t("onsite_later", { date: date(m.onsite_from, { day: "numeric", month: "long" }) })}</p>}</div>
      {m.brief && <div className={card}><div className="eyebrow">{t("brief")}</div><p className="whitespace-pre-wrap text-sm">{m.brief}</p></div>}
      {m.timeline.length > 0 && <div className={`${card} divide-y divide-border`}><div className="eyebrow">{t("timeline")}</div><Items items={m.timeline} /></div>}
      {(m.equipment_needed.length > 0 || m.equipment_note) && <div className={card}><div className="eyebrow">{t("equipment")}</div><div className="text-sm">{m.equipment_needed.join(", ")} {m.equipment_note}</div>{m.missing_equipment.length > 0 && <div className="mt-1 text-sm font-semibold text-amber-700">{t("equipment_missing", { list: m.missing_equipment.join(", ") })}</div>}</div>}
      <div className={card} data-testid="provider-terms"><div className="eyebrow mb-1">{t("terms_agreed")}</div>{[[t("rate"), money(m.agreed_rate)], [t("travel"), money(m.agreed_travel_fee)], [t("vat"), m.vat_mode === "subject" ? `${m.vat_rate} %` : t("vat_none")], [t("total"), money(m.vat_mode === "subject" ? m.total_ttc : m.total_ht)]].map(([l, x]) => <div key={l} className="flex justify-between py-0.5 text-sm"><span>{l}</span><b>{x}</b></div>)}</div>
      {m.team.length > 0 && <div className={card}><div className="eyebrow">{t("team")}</div>{m.team.map((x, i) => <div key={i} className="text-sm">{x.first_name} · {x.category} · {x.phone}</div>)}</div>}
      {!preview && <div className="flex flex-wrap items-center gap-2">
        {m.presence_confirmed_at ? <Badge ok>{t("presence_confirmed")}</Badge> : <Button onClick={() => act("confirm", {}, t("presence_confirmed"))} data-testid="provider-confirm">{t("confirm_presence")}</Button>}
        {m.has_invoice ? <Badge ok>{t("invoice_sent")} · {t(`pay_${m.payment_status || "pending"}`)}</Badge> : <Upload label={t("invoice_upload")} testid="provider-invoice-upload" onRef={(file) => act("invoice", { file }, t("invoice_sent"))} />}</div>}
      {m.has_music && <div data-testid="provider-music"><Button variant="outline" className="mb-3 w-full" onClick={() => setMu(!mu)} data-testid="provider-music-toggle">{t("mu_open")}</Button>{mu && <MusicPlan base={`/portal/provider/missions/${id}/music`} tr={tr} />}</div>}
      <Thread rows={m.messages} disabled={preview} onSend={(body) => api.post(`/portal/provider/missions/${id}/messages`, { body }).then(load)} />
    </div>
  );
}

function Missions() {
  const { t, date, money } = useP();
  const [d] = useLoad("/portal/provider/missions");
  const [open, setOpen] = useState(null);
  if (open) return <Mission id={open} onBack={() => setOpen(null)} />;
  if (!d) return null;
  if (!d.missions.length) return <Empty text={t("missions_empty")} />;
  return [["missions_upcoming", (m) => m.date >= d.today], ["missions_past", (m) => m.date < d.today]].map(([k, f]) => d.missions.filter(f).length > 0 && (
    <div key={k} className="mb-4" data-testid={`provider-${k}`}><div className="eyebrow mb-2">{t(k)}</div><div className="space-y-2">{d.missions.filter(f).map((m) => <button key={m.id} onClick={() => setOpen(m.id)} className={`${card} flex w-full items-center gap-3 text-left`} data-testid={`provider-mission-${m.id}`}>
      <div className="min-w-0 flex-1"><div className="font-semibold">{date(m.date, { weekday: "short", day: "numeric", month: "long", year: "numeric" })}</div><div className="text-sm text-muted-foreground">{m.category} · {m.venue_city} · {m.start_time}–{m.end_time}</div></div><div className="text-right"><Badge ok={m.status === "paid"}>{t(`s_${m.status}`)}</Badge><div className="mt-1 text-sm font-semibold">{money(m.vat_mode === "subject" ? m.total_ttc : m.total_ht)}</div></div></button>)}</div></div>));
}

function Requests() {
  const { t, date } = useP();
  const [rows] = useLoad("/portal/provider/requests");
  if (!rows) return null;
  if (!rows.length) return <Empty text={t("requests_empty")} />;
  return <div className="space-y-2" data-testid="provider-requests">{rows.map((r) => <div key={r.id} className={`${card} flex flex-wrap items-center gap-3`}><div className="min-w-0 flex-1"><div className="font-semibold">{date(r.date, { weekday: "short", day: "numeric", month: "long" })} · {r.city}</div><div className="text-sm text-muted-foreground">{r.category} · {r.start_time}–{r.end_time}</div></div>
    <Badge ok={r.retained}>{r.retained ? t("retained") : t(`r_${r.reply || "none"}`)}</Badge>{r.open && !r.retained && <Link className="text-sm font-semibold underline" to={r.url} target="_blank">{t("reply")}</Link>}</div>)}</div>;
}

function Calendar() {
  const { t, date, preview } = useP();
  const [rows, load] = useLoad("/portal/provider/unavailabilities");
  const [f, setF] = useState({ date: "", note: "" });
  if (!rows) return null;
  return (
    <div className={card} data-testid="provider-calendar"><div className="eyebrow mb-2">{t("unavail_title")}</div>
      {!rows.length && <p className="text-sm text-muted-foreground">{t("unavail_empty")}</p>}
      {rows.map((u) => <div key={u.id} className="flex items-center gap-2 border-b border-border py-2 text-sm last:border-0"><CalendarDays className="h-4 w-4" /><span className="flex-1">{date(u.date, { weekday: "short", day: "numeric", month: "long", year: "numeric" })} {u.note}</span>{u.source === "mission" ? <Badge>{t("src_mission")}</Badge> : u.source === "provider" && !preview && <button className="underline" onClick={() => api.delete(`/portal/provider/unavailabilities/${u.id}`).then(load)}>{t("remove")}</button>}</div>)}
      {!preview && <div className="mt-3 flex flex-wrap gap-2"><Input type="date" className="w-44" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} data-testid="provider-unavail-date" /><Input className="min-w-40 flex-1" placeholder={t("unavail_note")} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        <Button disabled={!f.date} onClick={() => api.post("/portal/provider/unavailabilities", f).then(() => { setF({ date: "", note: "" }); load(); }).catch(() => toast.error(t("error")))} data-testid="provider-unavail-add">{t("unavail_add")}</Button></div>}
    </div>
  );
}

function ProviderDocs() {
  const { t, date, preview } = useP();
  const [rows, load] = useLoad("/portal/provider/documents");
  const [f, setF] = useState({ type: "kbis", expires_at: "" });
  if (!rows) return null;
  return (
    <div className={card} data-testid="provider-documents">
      {!rows.length && <p className="text-sm text-muted-foreground">{t("pdocs_empty")}</p>}
      {rows.map((d) => <div key={d.id} className="flex items-center gap-2 border-b border-border py-2 text-sm last:border-0"><FileText className="h-4 w-4" /><span className="flex-1">{t(`d_${d.type}`)}{d.expires_at ? ` · ${t("expires")} ${date(d.expires_at, { day: "numeric", month: "short", year: "numeric" })}` : ""}</span><button className="underline" onClick={() => api.get(`/portal/provider/documents/${d.id}/link`).then((r) => openUrl(r.data.url))}>{t("open")}</button></div>)}
      {!preview && <div className="mt-3 flex flex-wrap items-center gap-2"><select className="h-9 rounded-lg border border-border bg-background px-2 text-sm" value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} aria-label={t("doc_type")}>{["kbis", "urssaf", "rc_pro", "autre"].map((k) => <option key={k} value={k}>{t(`d_${k}`)}</option>)}</select>
        <Input type="date" className="w-44" value={f.expires_at} onChange={(e) => setF({ ...f, expires_at: e.target.value })} aria-label={t("expires")} /><Upload label={t("upload_pdf")} testid="provider-doc-upload" onRef={(file) => api.post("/portal/provider/documents", { ...f, file }).then(load).catch(() => toast.error(t("error")))} /></div>}
    </div>
  );
}

function Profile() {
  const { t, preview } = useP();
  const [d, load] = useLoad("/portal/provider/profile");
  const [f, setF] = useState(null);
  useEffect(() => { if (d) setF(d.profile); }, [d]);
  if (!d || !f) return null;
  const num = ["base_rate", "travel_fee_amount", "radius_km"];
  const submit = () => api.post("/portal/provider/profile/changes", Object.fromEntries([...num.map((k) => [k, Number(f[k]) || 0]), ["base_city", f.base_city || ""]])).then(() => { toast.success(t("changes_sent")); load(); }).catch(() => toast.error(t("error")));
  return (
    <div className="space-y-4" data-testid="provider-profile">
      <div className={card}><div className="eyebrow">{t("profile_title")}</div><p className="mb-3 text-sm text-muted-foreground">{t("profile_note")}</p>
        <div className="grid grid-cols-2 gap-3">{[...num, "base_city"].map((k) => <label key={k} className="text-xs font-medium text-muted-foreground">{t(k)}<Input disabled={preview} type={num.includes(k) ? "number" : "text"} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`provider-profile-${k}`} /></label>)}</div>
        {!preview && <Button className="mt-3" onClick={submit} data-testid="provider-profile-submit">{t("submit_changes")}</Button>}</div>
      {d.changes.length > 0 && <div className={card}><div className="eyebrow mb-1">{t("history")}</div>{d.changes.map((c) => <div key={c.id} className="flex justify-between py-1 text-sm"><span>{Object.entries(c.changes).map(([k, v]) => `${t(k)} : ${v}`).join(" · ")}</span><Badge ok={c.status === "approved"}>{t(`c_${c.status}`)}</Badge></div>)}</div>}
    </div>
  );
}

// ---------- Commun ----------
function Account() {
  const { t, me, reload, preview } = useP();
  const { signOut } = useClerk();
  const [f, setF] = useState({ first_name: me.first_name, last_name: me.last_name, phone: me.phone });
  const patch = (b) => api.patch("/portal/account", b).then(() => { toast.success(t("saved")); reload(); }).catch(() => toast.error(t("error")));
  const exp = () => api.get("/portal/account/export").then((r) => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" })); a.download = "export.json"; a.click(); });
  return (
    <div className="space-y-4" data-testid="portal-account">
      <div className={card}><div className="eyebrow mb-2">{t("account_title")}</div><div className="grid grid-cols-2 gap-3">{["first_name", "last_name", "phone"].map((k) => <label key={k} className="text-xs font-medium text-muted-foreground">{t(k)}<Input disabled={preview} value={f[k] || ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} data-testid={`account-${k}`} /></label>)}
        <label className="text-xs font-medium text-muted-foreground">{t("language")}<select disabled={preview} className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground" value={me.language.startsWith("fr") ? "fr-FR" : me.language} onChange={(e) => patch({ language: e.target.value })} data-testid="account-language"><option value="fr-FR">Français</option><option value="en-US">English (US)</option><option value="en-GB">English (UK)</option></select></label></div>
        <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" disabled={preview} checked={me.notifications.email !== false} onChange={(e) => patch({ notify_email: e.target.checked })} />{t("notifications")}</label>
        {!preview && <Button className="mt-3" onClick={() => patch(f)} data-testid="account-save">{t("save")}</Button>}</div>
      {!preview && <div className={`${card} flex flex-wrap gap-2`}><Button variant="outline" onClick={() => signOut()} data-testid="account-sign-out">{t("sign_out")}</Button>
        <Button variant="outline" onClick={() => api.post("/portal/account/logout-all").then(() => { toast.success(t("logout_all_done")); signOut(); })} data-testid="account-logout-all">{t("logout_all")}</Button>
        <Button variant="outline" onClick={exp} data-testid="account-export">{t("export_data")}</Button><Button variant="ghost" onClick={() => api.post("/portal/account/delete-request").then(() => toast.success(t("delete_request_done")))} data-testid="account-delete-request">{t("delete_request")}</Button></div>}
    </div>
  );
}

function Terms({ me, tr, reload }) {
  const { t } = tr;
  const [f, setF] = useState({ first_name: me.first_name || "", last_name: me.last_name || "", accept: false });
  return (
    <div className="mx-auto max-w-md p-6" data-testid="portal-terms"><h1 className="text-3xl font-bold">{t("terms_title")}</h1><p className="mt-2 text-sm text-muted-foreground">{t("terms_intro")}</p>
      <div className="mt-4 space-y-3"><Input placeholder={t("first_name")} value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} data-testid="terms-first-name" /><Input placeholder={t("last_name")} value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} data-testid="terms-last-name" />
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={f.accept} onChange={(e) => setF({ ...f, accept: e.target.checked })} data-testid="terms-accept" /><span>{t("terms_accept")} — <Link className="underline" target="_blank" to={`/legal/${me.org.id}/privacy`}>{t("privacy")}</Link></span></label>
        <Button className="w-full" disabled={!f.accept || !f.first_name.trim()} onClick={() => api.post("/portal/terms", { ...f, language: me.language }).then(reload).catch(() => toast.error(t("error")))} data-testid="terms-submit">{t("terms_continue")}</Button></div></div>
  );
}

const PROVIDER_TABS = [["home", Home], ["missions", Briefcase], ["dj", Briefcase], ["agenda", CalendarDays], ["documents", FileText], ["space", User]];

export default function Portal({ viewAs }) {
  const [me, setMe] = useState(null);
  const [lang, setLang] = useState(null);
  const [tabs, setTabs] = useState([]);
  const [tab, setTab] = useState(null);
  const [wedding, setWedding] = useState(undefined); // espace mariage (module Wedding planner) : prioritaire pour les mariés
  const [classic, setClassic] = useState(false);
  const reload = useCallback(() => api.get("/portal/me").then((r) => { setMe(r.data); setLang((l) => (viewAs && l) || r.data.language); }).catch(() => toast.error("Erreur / Error")), [viewAs]);
  useEffect(() => { if (viewAs) api.defaults.headers.common["X-View-As"] = viewAs; reload(); return () => { delete api.defaults.headers.common["X-View-As"]; }; }, [viewAs, reload]);
  const tr = useMemo(() => makeT(lang || "fr-FR"), [lang]);
  useEffect(() => { if (me?.role === "client" && !me.terms_required) loadWedding().then(setWedding); else if (me) setWedding(null); }, [me]);
  if (!me || !lang) return null;
  const { t } = tr;
  if (me.terms_required) return <Terms me={me} tr={tr} reload={reload} />;
  const client = me.role === "client";
  if (client && wedding === undefined) return null;
  if (client && wedding && !classic) return <CoupleSpace home={wedding} onClassic={() => { setClassic(true); setTab("home"); }} onAccount={() => { setClassic(true); setTab("account"); }} />;
  const cur = tab || "home";
  const nav = client ? tabs : PROVIDER_TABS.map(([k, icon]) => ({ key: k, label: t(`tab_${k}`), icon }));
  return (
    <P.Provider value={{ ...tr, me, reload, preview: me.preview, setTabs, tab: cur, setTab }}>
      <div className="mx-auto min-h-screen max-w-xl bg-background px-4 pb-32 pt-4" data-testid={`portal-${me.role}`}>
        {me.preview && <div className="mb-3 flex items-center justify-between rounded-2xl bg-amber-500 px-4 py-2 text-sm font-semibold text-white" data-testid="preview-banner">{t("preview_banner")}<button className="underline" onClick={() => setLang(lang.startsWith("fr") ? "en-US" : "fr-FR")} data-testid="preview-lang">{lang.startsWith("fr") ? "EN" : "FR"}</button></div>}
        <header className="mb-4 flex items-center justify-between"><span className="font-brand text-lg">{me.org.name}</span>{wedding && classic ? <button className="text-sm underline" onClick={() => setClassic(false)} data-testid="back-to-wedding">{lang.startsWith("fr") ? "Mon espace mariage" : "My wedding space"}</button> : <span className="text-sm text-muted-foreground">{me.name}</span>}</header>
        {cur === "account" ? <Account /> : client ? <Client /> : cur === "home" ? <StaffHome tr={tr} go={setTab} /> : cur === "dj" ? <DjSpace tr={tr} /> : cur === "missions" ? <div className="space-y-6"><Missions /><Positions tr={tr} /><Requests /></div> : cur === "agenda" ? <div className="space-y-4"><Agenda tr={tr} preview={me.preview} /><Calendar /></div> : cur === "documents" ? <ProviderDocs /> : <div className="space-y-4"><Space tr={tr} preview={me.preview} /><MySocial base="/portal/provider/social" portal /><Profile /><Account /></div>}
        <footer className="mt-8 text-center text-xs text-muted-foreground"><Link className="underline" target="_blank" to={`/legal/${me.org.id}/privacy`}>{t("privacy")}</Link> · <Link className="underline" target="_blank" to={`/legal/${me.org.id}/legal`}>{t("legal")}</Link></footer>
        <nav className="fixed inset-x-3 bottom-3 z-40 mx-auto flex max-w-xl overflow-x-auto rounded-3xl border border-border bg-card px-1.5 py-2 shadow-lg" data-testid="portal-nav">
          {[...nav, ...(client ? [{ key: "account", label: t("tab_account"), icon: User }] : [])].map((n) => <button key={n.key} onClick={() => setTab(n.key)} data-testid={`portal-tab-${n.key}`} className={`flex min-w-[64px] flex-1 flex-col items-center gap-1 rounded-2xl py-1.5 text-[11px] ${cur === n.key ? "font-semibold text-foreground" : "text-muted-foreground"}`}><n.icon className={`h-5 w-5 ${cur === n.key ? "text-primary" : ""}`} /><span className="max-w-full truncate">{n.label}</span></button>)}
        </nav>
      </div>
    </P.Provider>
  );
}

export function PortalPreview() {
  const { uid } = useParams();
  return <Portal viewAs={uid} />;
}

export function LegalPage() {
  const { org, page } = useParams();
  const [d, setD] = useState(null);
  const [en, setEn] = useState(!navigator.language.startsWith("fr"));
  useEffect(() => { api.get(`/public/legal/${org}/${page}`).then((r) => setD(r.data)).catch(() => setD({ fr: "", en: "" })); }, [org, page]);
  if (!d) return null;
  const tr = makeT(en ? "en-US" : "fr-FR");
  return <div className="mx-auto max-w-2xl p-6" data-testid="legal-page"><div className="flex justify-between"><span className="font-brand">{d.org}</span><button className="underline" onClick={() => setEn(!en)}>{en ? "FR" : "EN"}</button></div><h1 className="mt-4 text-3xl font-bold">{tr.t(page === "privacy" ? "privacy" : "legal")}</h1><p className="mt-4 whitespace-pre-wrap text-sm">{(en && d.en) || d.fr || "—"}</p></div>;
}
