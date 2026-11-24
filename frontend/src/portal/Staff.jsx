import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SignUp, useAuth } from "@clerk/react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { makeT } from "@/portal/tr";

const card = "rounded-3xl border border-border bg-card p-5";
const detail = (e, t) => (typeof e.response?.data?.detail === "string" ? e.response.data.detail : t("error"));
const open = (u) => window.open(process.env.REACT_APP_BACKEND_URL + u, "_blank", "noopener");
const Chip = ({ children, ok }) => <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${ok ? "bg-emerald-500/10 text-emerald-700" : "bg-secondary"}`}>{children}</span>;

function useGet(path, t) {
  const [d, setD] = useState(null);
  const load = useCallback(() => api.get(path).then((r) => setD(r.data)).catch((e) => { setD(false); if (e.response?.status !== 404) toast.error(t("error")); }), [path, t]);
  useEffect(() => { load(); }, [load]);
  return [d, load];
}

export function StaffHome({ tr, go }) {
  const { t, date } = tr;
  const [d] = useGet("/portal/provider/home", t);
  if (!d) return null;
  const Row = ({ m }) => <button onClick={() => go("missions")} className="flex w-full justify-between py-1.5 text-left text-sm"><span>{date(m.date, { weekday: "short", day: "numeric", month: "long" })} · {m.category}</span><b>{m.start_time}–{m.end_time}</b></button>;
  return (
    <div className="space-y-4" data-testid="staff-home">
      <h1 className="text-3xl font-bold">{t("st_hello", { name: d.first_name })}</h1>
      {["pending", "more_info"].includes(d.validation_status) && <div className="rounded-2xl bg-amber-500/10 p-4 text-sm text-amber-700" data-testid="staff-pending">{t("st_pending")}</div>}
      {d.completion_pct < 100 && <div className="text-xs text-muted-foreground">{t("st_completion", { n: d.completion_pct })}</div>}
      {d.invitations > 0 && <button className={`${card} w-full text-left font-semibold text-primary`} onClick={() => go("missions")} data-testid="staff-home-invitations">{t("st_invites", { n: d.invitations })}</button>}
      <div className="rounded-3xl bg-foreground p-6 text-background" data-testid="staff-next"><div className="text-xs uppercase tracking-widest opacity-70">{t("st_next")}</div>{d.next ? <><div className="mt-1 text-2xl font-bold">{date(d.next.date)}</div><div className="text-sm opacity-80">{d.next.category} · {d.next.venue_city} · {d.next.start_time}–{d.next.end_time}</div></> : <div className="mt-1 text-sm opacity-80">{t("st_none_next")}</div>}</div>
      {d.week.length > 0 && <div className={card}><div className="eyebrow mb-1">{t("st_week")}</div>{d.week.map((m) => <Row key={m.id} m={m} />)}</div>}
    </div>
  );
}

export function Positions({ tr }) {
  const { t, date, money } = tr;
  const [d, load] = useGet("/portal/provider/positions", t);
  const [f, setF] = useState({});
  if (!d) return null;
  const run = (p) => p.then(() => { setF({}); load(); }).catch((e) => toast.error(detail(e, t)));
  const body = (id) => ({ message: f[id]?.message || "", counter_rate: f[id]?.rate ? Number(f[id].rate) : null });
  const Fields = ({ id }) => <div className="mt-2 flex gap-2"><Input placeholder={t("st_message")} value={f[id]?.message || ""} onChange={(e) => setF({ ...f, [id]: { ...f[id], message: e.target.value } })} /><Input className="w-40" type="number" placeholder={t("st_counter")} value={f[id]?.rate || ""} onChange={(e) => setF({ ...f, [id]: { ...f[id], rate: e.target.value } })} /></div>;
  const Pos = ({ p, children }) => <div className={card} data-testid={`staff-position-${p.id}`}><div className="flex flex-wrap items-center gap-2"><b className="flex-1">{p.category} · {date(p.date, { weekday: "short", day: "numeric", month: "long" })}</b><span className="text-sm font-semibold">{money(p.rate)} {t(`st_rate_${p.rate_type}`)}</span></div><div className="text-sm text-muted-foreground">{p.venue_city} · {p.start_time}–{p.end_time}{p.dress ? ` · ${p.dress}` : ""}</div>{p.brief && <p className="mt-1 whitespace-pre-wrap text-sm">{p.brief}</p>}{children}</div>;
  return (
    <div className="space-y-3" data-testid="staff-positions">
      {d.invitations.length > 0 && <div className="eyebrow">{t("st_invitations")}</div>}
      {d.invitations.map((p) => <div key={p.id}>{Pos({ p, children: <>{Fields({ id: p.id })}<div className="mt-2 flex flex-wrap gap-2">{["accept", "conditional", "refuse"].map((r) => <Button key={r} size="sm" variant={r === "accept" ? "default" : "outline"} onClick={() => run(api.post(`/portal/provider/applications/${p.application_id}/reply`, { reply: r, ...body(p.id) }))} data-testid={`staff-reply-${r}-${p.id}`}>{t(`st_${r}`)}</Button>)}</div></> })}</div>)}
      <div className="eyebrow">{t("st_open")}</div>
      {!d.open.length && <p className="text-sm text-muted-foreground">{t("st_open_empty")}</p>}
      {d.open.map((p) => <div key={p.id}>{Pos({ p, children: <>{Fields({ id: p.id })}<Button size="sm" className="mt-2" onClick={() => run(api.post(`/portal/provider/positions/${p.id}/apply`, body(p.id)))} data-testid={`staff-apply-${p.id}`}>{t("st_apply")}</Button></> })}</div>)}
      {d.applications.length > 0 && <div className="eyebrow">{t("st_my_apps")}</div>}
      {d.applications.map((p) => <div key={p.id}>{Pos({ p, children: <><div className="mt-2"><Chip ok={p.status === "confirmed"}>{t(`st_a_${p.status}`)}</Chip></div></> })}</div>)}
    </div>
  );
}

export function Agenda({ tr, preview }) {
  const { t, date } = tr;
  const [d, load] = useGet("/portal/provider/agenda", t);
  const [f, setF] = useState({ date: "", title: "" });
  const [url, setUrl] = useState("");
  if (!d) return null;
  const days = Array.from({ length: 28 }, (_, i) => { const x = new Date(`${d.today}T12:00`); x.setDate(x.getDate() + i); return x.toISOString().slice(0, 10); });
  const tone = { mission: "bg-primary text-white", invitation: "border border-dashed border-primary text-primary", busy: "bg-secondary text-muted-foreground" };
  return (
    <div className="space-y-4" data-testid="staff-agenda">
      <div className={card}><div className="eyebrow mb-2">{t("st_agenda")}</div><div className="grid grid-cols-7 gap-1">{days.map((day) => <div key={day} className="min-h-16 rounded-xl border border-border p-1" data-testid={`agenda-day-${day}`}><div className="text-[10px] text-muted-foreground">{date(day, { day: "numeric", month: "short" })}</div>
        {d.items.filter((i) => i.date === day).map((i) => <div key={i.id} title={i.label} className={`mt-0.5 truncate rounded px-1 text-[10px] ${tone[i.kind]}`}>{i.kind === "busy" ? i.label || t("st_busy") : `${i.start_time} ${i.label}`}</div>)}</div>)}</div>
        <div className="mt-2 flex flex-wrap gap-3 text-xs">{["mission", "invitation", "busy"].map((k) => <span key={k} className={`rounded px-2 py-0.5 ${tone[k]}`}>{t(`st_k_${k}`)}</span>)}</div></div>
      {!preview && <div className={card}><div className="eyebrow mb-2">{t("st_busy_add")}</div><div className="flex flex-wrap gap-2"><Input type="date" className="w-44" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} data-testid="staff-busy-date" /><Input className="min-w-40 flex-1" placeholder={t("st_busy_title")} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} data-testid="staff-busy-title" />
        <Button disabled={!f.date} onClick={() => api.post("/portal/provider/busy", f).then(() => { setF({ date: "", title: "" }); load(); }).catch((e) => toast.error(detail(e, t)))} data-testid="staff-busy-add">{t("mu_add")}</Button></div></div>}
      {!preview && <div className={card}><div className="eyebrow mb-2">{t("st_ical")}</div>{url && <div className="mb-2 break-all font-mono text-xs" data-testid="staff-ical-url">{process.env.REACT_APP_BACKEND_URL + url}</div>}
        <div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => api.post("/portal/provider/ical/create").then((r) => setUrl(r.data.url))} data-testid="staff-ical-create">{t("st_ical_create")}</Button>{(d.ical || url) && <Button variant="ghost" size="sm" onClick={() => api.post("/portal/provider/ical/revoke").then(() => { setUrl(""); load(); })}>{t("st_ical_revoke")}</Button>}</div></div>}
    </div>
  );
}

export function Space({ tr, preview }) {
  const { t, date, money } = tr;
  const [d, load] = useGet("/portal/provider/space", t);
  const [ts, setTs] = useState(null);
  const [bank, setBank] = useState({ iban: "", ssn: "" });
  if (!d) return null;
  const run = (p, msg) => p.then(() => { toast.success(msg || t("saved")); setTs(null); load(); }).catch((e) => toast.error(detail(e, t)));
  const inter = d.employment_status === "intermittent";
  return (
    <div className="space-y-3" data-testid="staff-space">
      <div className="eyebrow">{t("st_hours")}</div>
      {inter && <p className="text-sm text-muted-foreground">{t("st_payroll_note")}</p>}
      {d.missions.map((m) => { const s = m.timesheet; const editing = ts?.id === m.id; return (
        <div key={m.id} className={card} data-testid={`staff-space-${m.id}`}><div className="flex flex-wrap items-center gap-2"><b className="flex-1">{date(m.date, { day: "numeric", month: "long", year: "numeric" })} · {m.category}</b>{s && <Chip ok={["validated", "paid"].includes(s.status)}>{t(`st_ts_${s.status}`)}</Chip>}</div>
          {s && <div className="text-sm text-muted-foreground">{s.start_time}–{s.end_time} · {s.hours} h · {money(s.total_ht)}{s.review_reason ? ` · ${s.review_reason}` : ""}</div>}
          {!preview && <div className="mt-2 flex flex-wrap gap-2">
            {m.past && (!s || ["declared", "refused"].includes(s.status)) && !editing && <Button size="sm" onClick={() => setTs({ id: m.id, start_time: s?.start_time || m.start_time, end_time: s?.end_time || m.end_time, break_min: s?.break_min ?? m.break_min, km: s?.km || 0, expenses: s?.expenses || 0, comment: s?.comment || "" })} data-testid={`staff-declare-${m.id}`}>{t("st_declare")}</Button>}
            {s?.status === "validated" && !inter && !m.invoice && <Button size="sm" onClick={() => run(api.post(`/portal/provider/missions/${m.id}/make-invoice`))} data-testid={`staff-make-invoice-${m.id}`}>{t("st_make_invoice")}</Button>}
            {m.invoice && <button className="text-sm font-semibold underline" onClick={() => open(m.invoice.url)} data-testid={`staff-invoice-${m.id}`}>{t("st_invoice", { n: m.invoice.number })} · {money(m.invoice.total_ttc)} · {t(m.invoice.status === "paid" ? "st_ts_paid" : "pay_pending")}</button>}
            {!m.past && m.status === "confirmed" && <Button size="sm" variant="ghost" onClick={() => { const reason = window.prompt(t("st_withdraw_reason")); if (reason) run(api.post(`/portal/provider/missions/${m.id}/withdraw`, { reason })); }} data-testid={`staff-withdraw-${m.id}`}>{t("st_withdraw")}</Button>}</div>}
          {editing && <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">{[["start_time", "time", "st_start"], ["end_time", "time", "st_end"], ["break_min", "number", "st_break"], ["km", "number", "st_km"], ["expenses", "number", "st_expenses"]].map(([k, type, l]) => <label key={k} className="text-xs text-muted-foreground">{t(l)}<Input type={type} value={ts[k]} onChange={(e) => setTs({ ...ts, [k]: e.target.value })} data-testid={`staff-ts-${k}`} /></label>)}
            <Textarea className="col-span-2 sm:col-span-3" rows={2} placeholder={t("st_comment")} value={ts.comment} onChange={(e) => setTs({ ...ts, comment: e.target.value })} />
            <Button onClick={() => run(api.put(`/portal/provider/missions/${m.id}/timesheet`, { ...ts, break_min: Number(ts.break_min) || 0, km: Number(ts.km) || 0, expenses: Number(ts.expenses) || 0 }))} data-testid="staff-ts-save">{t("save")}</Button></div>}
        </div>); })}
      {!preview && <div className={card}><div className="eyebrow mb-2">{t("st_bank")}{d.has_bank && <span className="ml-2 normal-case text-emerald-700">✓</span>}</div><div className="flex flex-wrap gap-2"><Input className="min-w-48 flex-1" placeholder={t("st_iban")} value={bank.iban} onChange={(e) => setBank({ ...bank, iban: e.target.value })} data-testid="staff-iban" />{inter && <Input className="min-w-48 flex-1" placeholder={t("st_ssn")} value={bank.ssn} onChange={(e) => setBank({ ...bank, ssn: e.target.value })} />}
        <Button variant="outline" disabled={!bank.iban && !bank.ssn} onClick={() => run(api.put("/portal/provider/bank", bank).then(() => setBank({ iban: "", ssn: "" })), t("st_bank_saved"))} data-testid="staff-bank-save">{t("save")}</Button></div></div>}
    </div>
  );
}

const J0 = { first_name: "", last_name: "", phone: "", categories: [], years: "", languages: "", driving_licence: false, has_vehicle: false, equipment_brought: "", base_city: "", radius_km: 50, employment_status: "freelance", base_rate: "", vat_mode: "not_applicable_293B", siret: "", conges_spectacles_number: "", bio: "", website: "", accept: false };

export function JoinPage() {
  const [sp] = useSearchParams();
  const org = sp.get("o") || "";
  const { isSignedIn, isLoaded } = useAuth();
  const [en, setEn] = useState(!navigator.language.startsWith("fr"));
  const [info, setInfo] = useState(null);
  const [step, setStep] = useState(1);
  const [f, setF] = useState(() => ({ ...J0, ...JSON.parse(localStorage.getItem("join_draft") || "{}") }));
  const { t } = makeT(en ? "en-US" : "fr-FR");
  useEffect(() => { api.get(`/public/join/${org}`).then((r) => setInfo(r.data)).catch(() => setInfo(false)); }, [org]);
  useEffect(() => { localStorage.setItem("join_draft", JSON.stringify(f)); }, [f]);
  if (info === null || !isLoaded) return null;
  if (!info) return <div className="p-10 text-center text-sm">{t("mu_g_notfound")}</div>;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const In = ({ k, l, type = "text" }) => <label className="block text-xs text-muted-foreground">{t(l)}<Input type={type} value={f[k]} onChange={set(k)} data-testid={`join-${k}`} /></label>;
  const send = () => api.post("/join", { ...f, org_id: org, years_experience: Object.fromEntries(f.categories.map((c) => [c, Number(f.years) || 0])), languages: f.languages.split(",").map((x) => x.trim()).filter(Boolean), radius_km: Number(f.radius_km) || 0, base_rate: Number(f.base_rate) || 0, language: en ? "en-US" : "fr-FR" })
    .then(() => { localStorage.removeItem("join_draft"); window.location.href = "/"; }).catch((e) => toast.error(detail(e, t)));
  return (
    <div className="mx-auto max-w-md p-6" data-testid="join-page"><div className="flex justify-between"><span className="font-brand">{info.org}</span><button className="text-sm underline" onClick={() => setEn(!en)}>{en ? "FR" : "EN"}</button></div>
      <h1 className="mt-3 text-3xl font-bold">{t("jn_title", { org: info.org })}</h1>
      {!isSignedIn ? <div className="mt-4"><p className="mb-3 text-sm text-muted-foreground">{t("jn_signup")}</p><SignUp routing="hash" forceRedirectUrl={window.location.href} signInForceRedirectUrl={window.location.href} /></div> : <div className="mt-4 space-y-3">
        <div className="text-xs text-muted-foreground">{t("jn_step", { n: step })}</div>
        {step === 1 && <>{In({ k: "first_name", l: "first_name", type: "text" })}{In({ k: "last_name", l: "last_name", type: "text" })}{In({ k: "phone", l: "phone", type: "text" })}</>}
        {step === 2 && <><div className="text-xs text-muted-foreground">{t("jn_jobs")}</div><div className="flex flex-wrap gap-1.5">{info.categories.map((c) => <button key={c.key} onClick={() => setF({ ...f, categories: f.categories.includes(c.key) ? f.categories.filter((x) => x !== c.key) : [...f.categories, c.key] })} className={`rounded-full px-3 py-1 text-xs ${f.categories.includes(c.key) ? "bg-primary text-white" : "bg-secondary"}`} data-testid={`join-cat-${c.key}`}>{c.label}</button>)}</div>
          {In({ k: "years", l: "jn_years", type: "number" })}{In({ k: "languages", l: "jn_langs", type: "text" })}<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.driving_licence} onChange={set("driving_licence")} />{t("jn_licence")}</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.has_vehicle} onChange={set("has_vehicle")} />{t("jn_vehicle")}</label>{In({ k: "equipment_brought", l: "jn_gear", type: "text" })}</>}
        {step === 3 && <>{In({ k: "base_city", l: "base_city", type: "text" })}{In({ k: "radius_km", l: "radius_km", type: "number" })}<label className="block text-xs text-muted-foreground">{t("jn_status")}<select className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground" value={f.employment_status} onChange={set("employment_status")} data-testid="join-status">{["freelance", "intermittent", "other"].map((k) => <option key={k} value={k}>{t(`jn_${k}`)}</option>)}</select></label>
          {In({ k: "base_rate", l: "jn_rate", type: "number" })}{f.employment_status === "freelance" ? <>{In({ k: "siret", l: "jn_siret", type: "text" })}<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.vat_mode === "subject"} onChange={(e) => setF({ ...f, vat_mode: e.target.checked ? "subject" : "not_applicable_293B" })} />{t("jn_vat")}</label></> : f.employment_status === "intermittent" && In({ k: "conges_spectacles_number", l: "jn_cs", type: "text" })}</>}
        {step === 4 && <><label className="block text-xs text-muted-foreground">{t("jn_bio")}<Textarea rows={4} value={f.bio} onChange={set("bio")} data-testid="join-bio" /></label>{In({ k: "website", l: "jn_site", type: "text" })}<label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={f.accept} onChange={set("accept")} data-testid="join-accept" /><span>{t("terms_accept")} — <a className="underline" target="_blank" rel="noreferrer" href={`/legal/${org}/privacy`}>{t("privacy")}</a></span></label></>}
        <div className="flex gap-2">{step > 1 && <Button variant="outline" onClick={() => setStep(step - 1)}>{t("back")}</Button>}{step < 4 ? <Button className="flex-1" disabled={(step === 1 && !(f.first_name && f.last_name && f.phone.length > 5)) || (step === 2 && !f.categories.length)} onClick={() => setStep(step + 1)} data-testid="join-next">{t("jn_next")}</Button> : <Button className="flex-1" disabled={!f.accept} onClick={send} data-testid="join-send">{t("jn_send")}</Button>}</div></div>}
    </div>
  );
}
