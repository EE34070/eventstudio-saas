import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { QRCodeSVG } from "qrcode.react";
import { ChevronDown, ChevronUp, GripVertical, Lock, Music as MusicIcon, Plus, Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { api, downloadPdf } from "@/lib/api";
import { makeT } from "@/portal/tr";

const GENRES = ["pop", "rock", "80s", "2000s", "rap", "electro", "latino", "french", "funk", "rnb", "reggaeton", "jazz"];
const TAGS = ["chill", "festive", "romantic", "lounge", "80s", "elegant"];
const INFO = ["languages", "ages", "dancers", "constraints"];
const card = "rounded-3xl border border-border bg-card p-5";
const dur = (ms) => (ms ? `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}` : "");
const pick = (p) => ({ moments: p.moments, genre_preferences: p.genre_preferences || {}, banned: p.banned || [], useful_info: p.useful_info || {}, guest_requests_enabled: !!p.guest_requests_enabled });
const detail = (e) => (typeof e.response?.data?.detail === "string" ? e.response.data.detail : "");

function AddTrack({ base, tr, spotify, onAdd }) {
  const { t } = tr;
  const [f, setF] = useState({ title: "", artist: "" });
  const [res, setRes] = useState([]);
  useEffect(() => {
    if (!spotify || f.title.length < 2 || f.title.startsWith("http")) { setRes([]); return undefined; }
    const id = setTimeout(() => api.get(`${base}/search`, { params: { q: f.title } }).then((r) => setRes(r.data.results)).catch(() => {}), 350);
    return () => clearTimeout(id);
  }, [f.title, spotify, base]);
  const done = (x) => { onAdd(x); setF({ title: "", artist: "" }); setRes([]); };
  const add = async () => {
    const v = f.title.trim();
    if (!v) return;
    if (!v.startsWith("https://")) return done({ title: v, artist: f.artist, source: "manual" });
    try { const r = (await api.post(`${base}/resolve`, { url: v })).data; done({ title: r.title || v.slice(0, 200), artist: r.artist || f.artist, url: v, platform: r.platform, artwork_url: r.artwork_url, source: "link" }); } catch { done({ title: v.slice(0, 200), artist: f.artist, url: v, source: "link" }); }
  };
  return (
    <div className="mt-3">
      <div className="flex flex-wrap gap-2"><Input className="min-w-48 flex-1" value={f.title} placeholder={t("mu_track_placeholder")} onChange={(e) => setF({ ...f, title: e.target.value })} onKeyDown={(e) => e.key === "Enter" && add()} data-testid="music-track-title" />
        <Input className="w-40" value={f.artist} placeholder={t("mu_artist")} onChange={(e) => setF({ ...f, artist: e.target.value })} onKeyDown={(e) => e.key === "Enter" && add()} data-testid="music-track-artist" /><Button onClick={add} disabled={!f.title.trim()} data-testid="music-track-add"><Plus />{t("mu_add")}</Button></div>
      {!spotify && <p className="mt-1 text-xs text-muted-foreground">{t("mu_search_off")}</p>}
      {res.map((r) => <button key={r.url} onClick={() => done(r)} className="mt-1 flex w-full items-center gap-2 rounded-xl bg-secondary p-2 text-left text-sm">{r.artwork_url && <img src={r.artwork_url} alt="" className="h-9 w-9 rounded" />}<span className="flex-1"><b>{r.title}</b> — {r.artist}</span><span className="text-xs">{dur(r.duration_ms)}</span></button>)}
    </div>
  );
}

function AddPlaylist({ base, tr, onRef, onImport }) {
  const { t } = tr;
  const [url, setUrl] = useState("");
  const go = async (imp) => {
    const u = url.trim();
    if (!u.startsWith("https://")) return toast.error(t("mu_https"));
    setUrl("");
    if (!imp) return onRef({ url: u, mode: "reference" });
    const r = (await api.post(`${base}/import`, { url: u }).catch(() => ({ data: { ok: false } }))).data;
    if (r.ok) { onImport(r.tracks, { url: u, platform: r.platform, mode: "imported", count: r.count, duration_ms: r.duration_ms }); return toast.success(t("mu_imported", { n: r.count })); }
    onRef({ url: u, platform: r.platform || "", mode: "reference" });
    return toast.warning(t(r.reason === "nokey" ? "mu_import_nokey" : "mu_import_failed"));
  };
  return <div className="mt-2 flex flex-wrap gap-2"><Input className="min-w-48 flex-1" value={url} placeholder={t("mu_playlist_placeholder")} onChange={(e) => setUrl(e.target.value)} data-testid="music-playlist-url" /><Button variant="outline" disabled={!url.trim()} onClick={() => go(true)} data-testid="music-playlist-import">{t("mu_import")}</Button><Button variant="ghost" disabled={!url.trim()} onClick={() => go(false)} data-testid="music-playlist-ref">{t("mu_reference")}</Button></div>;
}

export default function Music({ base, tr }) {
  const { t, date, en } = tr;
  const [plan, setPlan] = useState(null);
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(null);
  const [more, setMore] = useState(null);
  const [saved, setSaved] = useState("");
  const [ban, setBan] = useState("");
  const [cm, setCm] = useState("");
  const [dest, setDest] = useState({});
  const dirty = useRef(false);
  const apply = (p) => { setPlan(p); setD(pick(p)); dirty.current = false; };
  const load = useCallback(() => api.get(base).then((r) => apply(r.data)).catch(() => toast.error(t("error"))), [base, t]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!dirty.current || !d) return undefined;
    setSaved("saving");
    const id = setTimeout(() => api.put(base, d).then((r) => { dirty.current = false; setSaved("saved"); setPlan((p) => ({ ...p, ...r.data })); }).catch((e) => { setSaved("error"); toast.error(detail(e) || t("error")); }), 900);
    return () => clearTimeout(id);
  }, [d, base, t]);
  if (!plan || !d) return null;
  const ed = plan.editable;
  const dj = plan.role === "dj";
  const up = (fn) => { dirty.current = true; setD((c) => { const n = structuredClone(c); fn(n); return n; }); };
  const mom = (i, k, v) => up((c) => { c.moments[i][k] = v; });
  const moveMoment = (i, j) => j >= 0 && j < d.moments.length && up((c) => { const [x] = c.moments.splice(i, 1); c.moments.splice(j, 0, x); });
  const moveTrack = (fi, ti, toI, pos) => {
    if (fi !== toI && d.moments[toI].single_track_mode && d.moments[toI].tracks.length) return toast.error(t("mu_single_full"));
    return up((c) => { const [x] = c.moments[fi].tracks.splice(ti, 1); c.moments[toI].tracks.splice(pos ?? c.moments[toI].tracks.length, 0, x); });
  };
  const addTracks = (i, list, pl) => up((c) => { const m = c.moments[i]; const room = m.single_track_mode ? Math.max(0, 1 - m.tracks.length) : 300 - m.tracks.length; if (list.length > room) toast.error(t("mu_single_full")); m.tracks.push(...list.slice(0, room).map((x) => ({ priority: "nice", ...x }))); if (pl) m.playlists.push(pl); });
  const drop = (e, toI, pos) => { e.preventDefault(); e.stopPropagation(); const [k, a, b] = e.dataTransfer.getData("text/plain").split(":"); if (k === "t") moveTrack(+a, +b, toI, pos); else if (k === "m" && pos == null) moveMoment(+a, toI); };
  const act = (p, body, msg) => api.post(`${base}/${p}`, body).then(() => { toast.success(msg); load(); }).catch((e) => toast.error(detail(e) || t("error")));
  const total = d.moments.reduce((n, m) => n + m.tracks.length, 0);
  const comment = (m) => api.post(`${base}/moments/${m.id}/comments`, { body: cm }).then((r) => { setPlan((p) => ({ ...p, comments: [...p.comments, r.data] })); setCm(""); }).catch((e) => toast.error(detail(e) || t("error")));
  const decide = (s, action) => api.post(`${base}/suggestions/${s.id}`, { action, moment_id: dest[s.id] || "" }).then((r) => apply(r.data)).catch((e) => toast.error(detail(e) || t("error")));
  const guestUrl = plan.guest_url ? window.location.origin + plan.guest_url : "";
  return (
    <div className="space-y-4" data-testid="music-plan">
      <div className={card}>
        <div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-semibold" data-testid="music-status">{t(`mu_status_${plan.status}`)}</span>
          {plan.locked ? <span className="flex items-center gap-1 text-xs font-semibold text-amber-700" data-testid="music-locked"><Lock className="h-3 w-3" />{t("mu_locked")}</span> : plan.lock_date && <span className="text-xs text-muted-foreground">{t("mu_lock", { date: date(plan.lock_date, { day: "numeric", month: "long" }) })}</span>}
          <span className="ml-auto text-xs text-muted-foreground" data-testid="music-saved">{saved && t(`mu_save_${saved}`)}</span></div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-secondary"><div className="h-full bg-primary transition-[width]" style={{ width: `${plan.completion}%` }} /></div><div className="mt-1 text-xs text-muted-foreground" data-testid="music-completion">{t("mu_progress", { n: plan.completion })}</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {ed && plan.status === "draft" && <Button disabled={saved === "saving" || !total} onClick={() => window.confirm(t("mu_send_confirm", { n: total, m: d.moments.filter((m) => m.enabled && (m.tracks.length || m.playlists.length)).length })) && act("send", {}, t("mu_sent_ok"))} data-testid="music-send">{t("mu_send")}</Button>}
          {dj && plan.status === "sent" && <Button onClick={() => act("validate", {}, t("mu_validated_ok"))} data-testid="music-validate">{t("mu_validate")}</Button>}
          {plan.role === "staff" && plan.locked && <Button variant="outline" onClick={() => act("unlock", {}, t("mu_unlock"))} data-testid="music-unlock">{t("mu_unlock")}</Button>}
          <Button variant="outline" onClick={() => downloadPdf(`${base}/pdf`, "feuille-de-route-dj.pdf")} data-testid="music-pdf">{t("mu_pdf")}</Button>
          {plan.role !== "client" && <Button variant="ghost" onClick={() => downloadPdf(`${base}/csv`, "morceaux.csv")} data-testid="music-csv">{t("mu_csv")}</Button>}
          {plan.role === "staff" && ed && !total && <select className="h-9 rounded-lg border border-border bg-background px-2 text-sm" value="" onChange={(e) => e.target.value && act("template", { key: e.target.value }, t("mu_save_saved"))} data-testid="music-template"><option value="">{t("mu_template")}</option>{Object.entries(plan.templates || {}).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>}
        </div>
      </div>

      {(ed || d.banned.length > 0) && <div className={`${card} border-red-500/40`} data-testid="music-banned"><div className="eyebrow mb-2 text-red-600">{t("mu_banned")}</div>
        <div className="flex flex-wrap gap-2">{d.banned.map((b, i) => <span key={i} className="flex items-center gap-1 rounded-full bg-red-500/10 px-3 py-1 text-sm font-semibold text-red-600">{b}{ed && <button aria-label="×" onClick={() => up((c) => { c.banned.splice(i, 1); })}>×</button>}</span>)}</div>
        {ed && <div className="mt-2 flex gap-2"><Input value={ban} placeholder={t("mu_banned_add")} onChange={(e) => setBan(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ban.trim() && (up((c) => { c.banned.push(ban.trim()); }), setBan(""))} data-testid="music-banned-input" /><Button variant="outline" disabled={!ban.trim()} onClick={() => { up((c) => { c.banned.push(ban.trim()); }); setBan(""); }} data-testid="music-banned-add">{t("mu_add")}</Button></div>}</div>}

      {d.moments.map((m, i) => (ed || m.enabled) && (
        <div key={m.id || i} className={`${card} ${m.enabled ? "" : "opacity-60"}`} onDragOver={(e) => e.preventDefault()} onDrop={(e) => ed && drop(e, i)} data-testid={`music-moment-${i}`}>
          <div className="flex items-center gap-2" draggable={ed} onDragStart={(e) => e.dataTransfer.setData("text/plain", `m:${i}`)}>
            {ed && <GripVertical className="h-4 w-4 shrink-0 cursor-grab text-muted-foreground" />}
            <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={() => setOpen(open === i ? null : i)} data-testid={`music-moment-toggle-${i}`}><MusicIcon className={`h-5 w-5 shrink-0 ${m.is_key_moment ? "text-amber-600" : "text-primary"}`} /><span className="min-w-0 flex-1"><b className="block truncate">{(en && m.name_en) || m.name}</b>
              <span className="text-xs text-muted-foreground">{[m.scheduled_time, t("mu_tracks", { n: m.tracks.length }), m.is_key_moment && t("mu_key"), m.single_track_mode && t("mu_single")].filter(Boolean).join(" · ")}</span></span></button>
            {ed && <><button aria-label="↑" onClick={() => moveMoment(i, i - 1)}><ChevronUp className="h-4 w-4" /></button><button aria-label="↓" onClick={() => moveMoment(i, i + 1)}><ChevronDown className="h-4 w-4" /></button></>}
          </div>
          {open === i && <div className="mt-4">
            {ed ? <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <label className="col-span-2 text-xs text-muted-foreground">{t("mu_name")}<Input value={(en && m.name_en) || m.name} onChange={(e) => up((c) => { c.moments[i].name = e.target.value; c.moments[i].name_en = ""; })} data-testid={`music-moment-name-${i}`} /></label>
              <label className="text-xs text-muted-foreground">{t("mu_time")}<Input type="time" value={m.scheduled_time} onChange={(e) => mom(i, "scheduled_time", e.target.value)} /></label>
              <label className="text-xs text-muted-foreground">{t("mu_duration")}<Input type="number" min="0" value={m.duration_min || ""} onChange={(e) => mom(i, "duration_min", Number(e.target.value) || 0)} /></label>
              <label className="col-span-2 text-xs text-muted-foreground sm:col-span-4">{t("mu_mood")}<Input value={m.mood} onChange={(e) => mom(i, "mood", e.target.value)} /></label>
              <div className="col-span-2 flex flex-wrap gap-1.5 sm:col-span-4">{TAGS.map((k) => <button key={k} onClick={() => mom(i, "mood_tags", m.mood_tags.includes(k) ? m.mood_tags.filter((x) => x !== k) : [...m.mood_tags, k])} className={`rounded-full px-3 py-1 text-xs ${m.mood_tags.includes(k) ? "bg-primary text-white" : "bg-secondary"}`}>{t(`mu_tag_${k}`)}</button>)}</div>
              <label className="col-span-2 text-xs text-muted-foreground sm:col-span-4">{t("mu_instructions")}<Textarea rows={2} value={m.instructions} onChange={(e) => mom(i, "instructions", e.target.value)} data-testid={`music-moment-instructions-${i}`} /></label>
              <div className="col-span-2 flex flex-wrap items-center gap-4 text-sm sm:col-span-4"><label className="flex items-center gap-2"><Switch checked={m.enabled} onCheckedChange={(v) => mom(i, "enabled", v)} />{t("mu_enabled")}</label><label className="flex items-center gap-2"><Switch checked={m.is_key_moment} onCheckedChange={(v) => mom(i, "is_key_moment", v)} />{t("mu_key")}</label>
                <label className="flex items-center gap-2"><Switch checked={m.single_track_mode} disabled={m.tracks.length > 1} onCheckedChange={(v) => mom(i, "single_track_mode", v)} />{t("mu_single")}</label>
                <button className="ml-auto flex items-center gap-1 text-xs text-red-600" onClick={() => window.confirm(t("mu_delete_moment")) && (setOpen(null), up((c) => { c.moments.splice(i, 1); }))} data-testid={`music-moment-delete-${i}`}><Trash2 className="h-3.5 w-3.5" />{t("mu_delete_moment")}</button></div>
            </div> : <div className="space-y-1 text-sm">{(m.mood || m.mood_tags.length > 0) && <p><b>{t("mu_mood")} :</b> {[m.mood, ...m.mood_tags.map((k) => t(`mu_tag_${k}`))].filter(Boolean).join(" · ")}</p>}{m.instructions && <p className="whitespace-pre-wrap"><b>{t("mu_instructions")} :</b> {m.instructions}</p>}</div>}

            <div className="mt-3">{!m.tracks.length && !m.playlists.length && <p className="text-sm text-muted-foreground">{t("mu_empty_moment")}</p>}
              {m.tracks.map((x, j) => (
                <div key={x.id || j} className="border-b border-border py-2 last:border-0" draggable={ed} onDragStart={(e) => { e.stopPropagation(); e.dataTransfer.setData("text/plain", `t:${i}:${j}`); }} onDragOver={(e) => e.preventDefault()} onDrop={(e) => ed && drop(e, i, j)} data-testid={`music-track-${i}-${j}`}>
                  <div className="flex items-center gap-2 text-sm">{ed && <GripVertical className="h-4 w-4 shrink-0 cursor-grab text-muted-foreground" />}{x.artwork_url && <img src={x.artwork_url} alt="" className="h-9 w-9 rounded object-cover" />}
                    <button className="min-w-0 flex-1 text-left" onClick={() => setMore(more === `${i}:${j}` ? null : `${i}:${j}`)}><b className="block truncate">{x.title}</b><span className="block truncate text-xs text-muted-foreground">{[x.artist, dur(x.duration_ms), x.start_at && `${t("mu_start_at")} ${x.start_at}`, x.version_note, x.note].filter(Boolean).join(" · ")}</span></button>
                    {x.url && <a className="text-xs underline" href={x.url} target="_blank" rel="noreferrer">{x.platform || "↗"}</a>}
                    <button disabled={!ed} title={t(x.priority === "must" ? "mu_must" : "mu_nice")} onClick={() => up((c) => { c.moments[i].tracks[j].priority = x.priority === "must" ? "nice" : "must"; })} data-testid={`music-track-priority-${i}-${j}`}><Star className={`h-4 w-4 ${x.priority === "must" ? "fill-amber-500 text-amber-500" : "text-muted-foreground"}`} /></button>
                    {ed && <button aria-label="×" onClick={() => up((c) => { c.moments[i].tracks.splice(j, 1); })} data-testid={`music-track-remove-${i}-${j}`}><Trash2 className="h-4 w-4" /></button>}</div>
                  {x.preview_url && <audio className="mt-1 h-8 w-full" controls preload="none" src={x.preview_url} />}
                  {ed && more === `${i}:${j}` && <div className="mt-2 grid grid-cols-2 gap-2">{[["version_note", "mu_version"], ["start_at", "mu_start_at"], ["note", "mu_note"]].map(([k, l]) => <Input key={k} placeholder={t(l)} value={x[k] || ""} onChange={(e) => up((c) => { c.moments[i].tracks[j][k] = e.target.value; })} data-testid={`music-track-${k}-${i}-${j}`} />)}
                    <select className="h-10 rounded-lg border border-border bg-background px-2 text-sm" value="" onChange={(e) => e.target.value !== "" && (setMore(null), moveTrack(i, j, +e.target.value))} aria-label={t("mu_move_to")}><option value="">{t("mu_move_to")}</option>{d.moments.map((o, k) => k !== i && <option key={k} value={k}>{(en && o.name_en) || o.name}</option>)}</select></div>}
                </div>))}
              {m.playlists.map((pl, j) => <div key={pl.id || j} className="flex items-center gap-2 py-1 text-sm"><span className="text-xs font-semibold">{t("mu_playlist")}</span><a className="min-w-0 flex-1 truncate underline" href={pl.url} target="_blank" rel="noreferrer">{pl.url}</a>{pl.count > 0 && <span className="text-xs">{t("mu_tracks", { n: pl.count })} · {dur(pl.duration_ms)}</span>}{ed && <button aria-label="×" onClick={() => up((c) => { c.moments[i].playlists.splice(j, 1); })}><Trash2 className="h-4 w-4" /></button>}</div>)}
              {ed && !(m.single_track_mode && m.tracks.length > 0) && <><AddTrack base={base} tr={tr} spotify={plan.spotify} onAdd={(x) => addTracks(i, [x])} />{!m.single_track_mode && <AddPlaylist base={base} tr={tr} onRef={(pl) => up((c) => { c.moments[i].playlists.push(pl); })} onImport={(list, pl) => addTracks(i, list, pl)} />}</>}
            </div>
            {m.id && <div className="mt-4 rounded-2xl bg-secondary/60 p-3" data-testid={`music-comments-${i}`}><div className="eyebrow mb-1">{t("mu_comments")}</div>{plan.comments.filter((c) => c.moment_id === m.id).map((c) => <div key={c.id} className="py-1 text-sm"><b>{c.by}</b> <span className="text-xs text-muted-foreground">{c.role}</span><div className="whitespace-pre-wrap">{c.body}</div></div>)}
              <div className="mt-1 flex gap-2"><Input value={cm} placeholder={t("mu_comment_placeholder")} onChange={(e) => setCm(e.target.value)} data-testid={`music-comment-input-${i}`} /><Button variant="outline" disabled={!cm.trim()} onClick={() => comment(m)} data-testid={`music-comment-send-${i}`}>{t("send")}</Button></div></div>}
          </div>}
        </div>))}
      {ed && <Button variant="outline" className="w-full" onClick={() => { up((c) => { c.moments.push({ id: "", name: t("mu_new_moment"), name_en: "", enabled: true, is_key_moment: false, single_track_mode: false, scheduled_time: "", duration_min: 0, mood: "", mood_tags: [], instructions: "", tracks: [], playlists: [] }); }); setOpen(d.moments.length); }} data-testid="music-moment-add"><Plus />{t("mu_add_moment")}</Button>}

      <div className={card} data-testid="music-genres"><div className="eyebrow mb-2">{t("mu_genres")}</div>{GENRES.filter((g) => ed || d.genre_preferences[g]).map((g) => <div key={g} className="flex items-center gap-2 py-1 text-sm"><span className="flex-1">{t(`mu_genre_${g}`)}</span>
        {["love", "ok", "avoid"].map((lv) => (ed || d.genre_preferences[g] === lv) && <button key={lv} disabled={!ed} onClick={() => up((c) => { if (c.genre_preferences[g] === lv) delete c.genre_preferences[g]; else c.genre_preferences[g] = lv; })} data-testid={`music-genre-${g}-${lv}`} className={`rounded-full px-3 py-1 text-xs ${d.genre_preferences[g] === lv ? (lv === "avoid" ? "bg-red-500 text-white" : lv === "love" ? "bg-emerald-600 text-white" : "bg-foreground text-background") : "bg-secondary"}`}>{t(`mu_level_${lv}`)}</button>)}</div>)}</div>
      <div className={card} data-testid="music-info"><div className="eyebrow mb-2">{t("mu_info")}</div>{INFO.map((k) => (ed ? <label key={k} className="mb-2 block text-xs text-muted-foreground">{t(`mu_info_${k}`)}<Textarea rows={2} value={d.useful_info[k] || ""} onChange={(e) => up((c) => { c.useful_info[k] = e.target.value; })} data-testid={`music-info-${k}`} /></label> : d.useful_info[k] && <p key={k} className="text-sm"><b>{t(`mu_info_${k}`)} :</b> {d.useful_info[k]}</p>))}</div>

      {!dj && <div className={card} data-testid="music-guests"><div className="eyebrow mb-2">{t("mu_guests")}</div><label className="flex items-center gap-2 text-sm"><Switch disabled={!ed} checked={d.guest_requests_enabled} onCheckedChange={(v) => up((c) => { c.guest_requests_enabled = v; })} data-testid="music-guests-switch" />{t("mu_guests_enable")}</label>
        {d.guest_requests_enabled && guestUrl && <div className="mt-3 flex flex-wrap items-center gap-4"><QRCodeSVG value={guestUrl} size={96} /><div className="min-w-0 flex-1 text-sm"><div className="break-all font-mono text-xs" data-testid="music-guest-url">{guestUrl}</div><Button size="sm" variant="outline" className="mt-2" onClick={() => navigator.clipboard.writeText(guestUrl).then(() => toast.success(t("mu_guests_link")))}>{t("mu_guests_link")}</Button></div></div>}
        {(plan.suggestions || []).map((s) => <div key={s.id} className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-sm" data-testid={`music-suggestion-${s.id}`}><div className="min-w-40 flex-1"><b>{s.title}</b> {s.artist && `— ${s.artist}`}<div className="text-xs text-muted-foreground">{s.name}{s.url && <> · <a className="underline" href={s.url} target="_blank" rel="noreferrer">↗</a></>}</div></div>
          {ed && <><select className="h-9 rounded-lg border border-border bg-background px-2 text-sm" value={dest[s.id] || ""} onChange={(e) => setDest({ ...dest, [s.id]: e.target.value })}><option value="">{t("mu_choose_moment")}</option>{plan.moments.map((m) => <option key={m.id} value={m.id}>{(en && m.name_en) || m.name}</option>)}</select>
            <Button size="sm" disabled={!dest[s.id]} onClick={() => decide(s, "accept")}>{t("mu_accept")}</Button><Button size="sm" variant="ghost" onClick={() => decide(s, "refuse")}>{t("mu_refuse")}</Button></>}</div>)}</div>}
      {plan.activity.length > 0 && <details className={card}><summary className="eyebrow cursor-pointer">{t("mu_history")}</summary>{plan.activity.map((a, i) => <div key={i} className="py-0.5 text-xs text-muted-foreground">{new Date(a.at).toLocaleString(en ? "en-US" : "fr-FR")} · {a.by} · {t(`mu_act_${a.action}`)}</div>)}</details>}
    </div>
  );
}

export function GuestMusic() {
  const { token } = useParams();
  const [d, setD] = useState(null);
  const [en, setEn] = useState(false);
  const [f, setF] = useState({ name: "", title: "", artist: "", url: "", answer: "", website: "" });
  const [done, setDone] = useState(false);
  const load = useCallback(() => api.get(`/public/music/${token}`).then((r) => { setD(r.data); setEn(!navigator.language.startsWith("fr") || !r.data.language.startsWith("fr")); }).catch(() => setD(false)), [token]);
  useEffect(() => { load(); }, [load]);
  const { t } = makeT(en ? "en-US" : "fr-FR");
  if (d === null) return null;
  if (!d) return <div className="p-10 text-center text-sm" data-testid="guest-notfound">{t("mu_g_notfound")}</div>;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const send = () => {
    let dev = localStorage.getItem("guest_device");
    if (!dev) { dev = crypto.randomUUID(); localStorage.setItem("guest_device", dev); }
    api.post(`/public/music/${token}`, { ...f, answer: Number(f.answer) || 0, device: dev, exp: d.challenge.exp, sig: d.challenge.sig }).then(() => setDone(true)).catch((e) => { toast.error(t(e.response?.status === 429 ? "mu_g_limit" : "error")); load(); });
  };
  return (
    <div className="mx-auto max-w-md p-6" data-testid="guest-music"><div className="flex justify-end"><button className="text-sm underline" onClick={() => setEn(!en)}>{en ? "FR" : "EN"}</button></div>
      <MusicIcon className="h-8 w-8 text-primary" /><h1 className="mt-2 text-3xl font-bold">{t("mu_g_title", { event: d.event })}</h1>
      {done ? <div className="mt-6"><p data-testid="guest-thanks">{t("mu_g_thanks")}</p><Button className="mt-4" variant="outline" onClick={() => { setDone(false); setF({ ...f, title: "", artist: "", url: "", answer: "" }); load(); }}>{t("mu_add")}</Button></div> : <div className="mt-6 space-y-3">
        <Input placeholder={t("mu_g_name")} value={f.name} onChange={set("name")} data-testid="guest-name" /><Input placeholder={t("mu_g_song")} value={f.title} onChange={set("title")} data-testid="guest-title" /><Input placeholder={t("mu_artist")} value={f.artist} onChange={set("artist")} data-testid="guest-artist" /><Input placeholder={t("mu_g_link")} value={f.url} onChange={set("url")} data-testid="guest-url" />
        <input className="hidden" tabIndex={-1} autoComplete="off" value={f.website} onChange={set("website")} aria-hidden="true" />
        <Input type="number" placeholder={t("mu_g_captcha", { a: d.challenge.a, b: d.challenge.b })} value={f.answer} onChange={set("answer")} data-testid="guest-captcha" />
        <Button className="w-full" disabled={!f.name.trim() || !f.title.trim() || !f.answer} onClick={send} data-testid="guest-send">{t("mu_g_send")}</Button></div>}
    </div>
  );
}
