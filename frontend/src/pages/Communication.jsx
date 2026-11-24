import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ChevronLeft, ChevronRight, Copy, Film, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader, Loading } from "@/components/common";
import { FileImg, openFile } from "@/lib/files";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/constants";
import { ko, sel, copy, chunked, RIGHTS, Requests } from "@/components/communication/shared";

const TABS = [["media", "Médiathèque"], ["collectes", "Collectes"], ["credits", "Crédits Instagram"], ["studio", "Studio"], ["calendrier", "Calendrier"], ["reglages", "Réglages"]];
const TYPES = { post: "Post", carrousel: "Carrousel", reel: "Reel", story: "Story" };
const PST = { idee: "Idée", brouillon: "Brouillon", pret: "Prêt", planifie: "Planifié", publie: "Publié" };
const POST = { title: "", brand_id: "", type: "post", event_id: "", asset_ids: [], caption_fr: "", caption_en: "", hashtags: [], credits_text: "", scheduled_at: "", status: "brouillon", permalink: "" };
const Badge = ({ a }) => <span title={a.blocked_reasons.join(" · ")} className={`rounded-full px-2 py-0.5 text-xs ${a.status === "publiable" ? "bg-emerald-500/15 text-emerald-700" : "bg-red-500/15 text-red-700"}`} data-testid={`media-status-${a.id}`}>{a.status === "publiable" ? "Publiable" : "Bloqué"}</span>;
const Thumb = ({ a, className }) => (a.thumb_ref ? <FileImg src={a.thumb_ref} alt={a.filename} className={className} /> : <div className={`${className} flex items-center justify-center bg-secondary`}><Film className="h-6 w-6 text-muted-foreground" /></div>);

function MediaEdit({ a, o, onClose, onSaved }) {
  const [f, setF] = useState({ event_id: a.event_id, brand_id: a.brand_id, author_name: a.author_name, author_handle: a.author_handle, rights: a.rights, rights_note: a.rights_note, tags: a.tags.join(", ") });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open onOpenChange={(x) => !x && onClose()}><DialogContent className="max-w-2xl" data-testid="media-dialog">
      <DialogHeader><DialogTitle className="truncate">{a.filename}</DialogTitle><DialogDescription>{a.kind === "video" ? `Vidéo · ${a.duration} s` : "Photo"} · {a.width}×{a.height} · {(a.size / 1048576).toFixed(1)} Mo{a.converted ? ` · ${a.converted}` : ""}</DialogDescription></DialogHeader>
      <div className="flex gap-4"><button onClick={() => openFile(a.file_ref)} data-testid="media-open"><Thumb a={a} className="h-40 w-40 rounded-xl object-cover" /></button>
        <div className="grid flex-1 grid-cols-2 gap-2 text-xs text-muted-foreground">
          <label>Événement<select className={`${sel} mt-1 w-full`} value={f.event_id} onChange={set("event_id")} data-testid="media-event"><option value="">—</option>{o.events.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}</select></label>
          <label>Marque<select className={`${sel} mt-1 w-full`} value={f.brand_id} onChange={set("brand_id")} data-testid="media-brand"><option value="">—</option>{o.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
          <label>Auteur<Input className="mt-1 h-9" value={f.author_name} onChange={set("author_name")} data-testid="media-author" /></label>
          <label>Instagram de l'auteur<Input className="mt-1 h-9" value={f.author_handle} onChange={set("author_handle")} data-testid="media-handle" /></label>
          <label>Droits<select className={`${sel} mt-1 w-full`} value={f.rights} onChange={set("rights")} data-testid="media-rights">{Object.entries(RIGHTS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label>Précision sur les droits<Input className="mt-1 h-9" value={f.rights_note} onChange={set("rights_note")} /></label>
          <label className="col-span-2">Mots-clés (séparés par des virgules)<Input className="mt-1 h-9" value={f.tags} onChange={set("tags")} data-testid="media-tags" /></label></div></div>
      {!!a.blocked_reasons.length && <div className="rounded-lg bg-red-500/10 p-2 text-xs text-red-700" data-testid="media-blocked-reasons">Bloqué : {a.blocked_reasons.join(" · ")}</div>}
      {o.write && <div className="flex justify-between"><Button variant="ghost" onClick={() => window.confirm("Placer ce média dans la Corbeille (30 jours) ?") && api.delete(`/communication/media/${a.id}`).then(onSaved).catch(ko)} data-testid="media-delete"><Trash2 />Supprimer</Button>
        <Button onClick={() => api.put(`/communication/media/${a.id}`, { ...f, tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean) }).then(onSaved).catch(ko)} data-testid="media-save">Enregistrer</Button></div>}
    </DialogContent></Dialog>);
}

function Media({ o, initialEvent }) {
  const [rows, setRows] = useState(null);
  const [flt, setFlt] = useState({ event_id: initialEvent || "", brand_id: "", kind: "", status: "", q: "" });
  const [picked, setPicked] = useState([]);
  const [edit, setEdit] = useState(null);
  const [ups, setUps] = useState([]);
  const input = useRef(null);
  const load = useCallback(() => api.get("/communication/media", { params: flt }).then((r) => setRows(r.data)).catch(ko), [flt]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);
  const pick = async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    for (const file of files) {
      const id = `${file.name}-${Date.now()}`;
      const set = (p) => setUps((c) => c.map((u) => (u.id === id ? { ...u, ...p } : u)));
      setUps((c) => [...c, { id, name: file.name, pct: 0, state: "" }]);
      try { const r = await chunked(api, "/communication/uploads", file, { event_id: flt.event_id, brand_id: flt.brand_id }, (pct) => set({ pct })); set({ pct: 100, state: r.duplicate ? "doublon : déjà dans la médiathèque" : "importé" }); } catch (x) { set({ state: x.response?.data?.detail || "échec" }); }
    }
    load();
  };
  const bulk = (patch) => api.put("/communication/media/bulk", { ids: picked, patch }).then(() => { setPicked([]); load(); toast.success("Médias mis à jour"); }).catch(ko);
  const F = (k, opts, all, tid) => <select className={sel} value={flt[k]} onChange={(e) => setFlt({ ...flt, [k]: e.target.value })} data-testid={tid}><option value="">{all}</option>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>;
  return (
    <div data-testid="comm-media">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {F("event_id", o.events.map((e) => [e.id, e.title]), "Tous les événements", "media-filter-event")}{F("brand_id", o.brands.map((b) => [b.id, b.name]), "Toutes les marques", "media-filter-brand")}
        {F("kind", [["image", "Photos"], ["video", "Vidéos"]], "Photos et vidéos", "media-filter-kind")}{F("status", [["publiable", "Publiable"], ["bloque", "Bloqué"]], "Tous statuts", "media-filter-status")}
        <Input className="h-9 w-52 bg-card" placeholder="Rechercher" value={flt.q} onChange={(e) => setFlt({ ...flt, q: e.target.value })} data-testid="media-search" /><span className="flex-1" />
        {o.write && <><input ref={input} type="file" hidden multiple accept="image/*,video/mp4,video/quicktime,video/webm,.heic,.heif" onChange={pick} data-testid="media-input" /><Button onClick={() => input.current.click()} data-testid="media-import"><Upload />Importer</Button></>}</div>
      {!o.video && <div className="mb-3 rounded-lg bg-amber-500/10 p-2 text-xs text-amber-700" data-testid="media-no-ffmpeg">ffmpeg absent du serveur : les vidéos sont importées sans durée ni image de couverture.</div>}
      {!!ups.length && <div className="card-soft mb-3 space-y-1 p-3 text-xs" data-testid="media-uploads">{ups.map((u) => <div key={u.id} className="flex items-center gap-2" data-testid="media-upload-row"><span className="w-56 truncate">{u.name}</span><span className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary"><span className="block h-full bg-primary" style={{ width: `${u.pct}%` }} /></span><span className="w-64 text-right" data-testid="media-upload-state">{u.state || `${u.pct} %`}</span></div>)}
        <button className="underline" onClick={() => setUps([])}>Masquer</button></div>}
      {o.write && !!picked.length && <div className="card-soft mb-3 flex flex-wrap items-center gap-2 p-3 text-sm" data-testid="media-bulk"><b>{picked.length} sélectionné(s)</b>
        {Object.entries(RIGHTS).map(([k, l]) => <Button key={k} size="sm" variant="outline" onClick={() => bulk({ rights: k })} data-testid={`media-bulk-rights-${k}`}>{l}</Button>)}
        <select className={sel} value="" onChange={(e) => e.target.value && bulk({ event_id: e.target.value })} data-testid="media-bulk-event"><option value="">Rattacher à un événement…</option>{o.events.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}</select>
        <select className={sel} value="" onChange={(e) => e.target.value && bulk({ brand_id: e.target.value })} data-testid="media-bulk-brand"><option value="">Marque…</option>{o.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>
        <button className="text-xs underline" onClick={() => setPicked([])}>Tout désélectionner</button></div>}
      {!rows ? <Loading /> : !rows.length ? <p className="card-soft p-6 text-sm text-muted-foreground" data-testid="media-empty">Aucun média. Importez des photos ou vidéos, ou lancez une collecte.</p> : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6" data-testid="media-grid">{rows.map((a) => (
          <div key={a.id} className="card-soft overflow-hidden" data-testid={`media-card-${a.id}`}>
            <div className="relative"><button className="block w-full" onClick={() => setEdit(a)} data-testid={`media-open-${a.id}`}><Thumb a={a} className="aspect-square w-full object-cover" /></button>
              {o.write && <input type="checkbox" className="absolute left-2 top-2 h-4 w-4" checked={picked.includes(a.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, a.id] : picked.filter((x) => x !== a.id))} data-testid={`media-pick-${a.id}`} />}
              {a.kind === "video" && <span className="absolute bottom-2 right-2 rounded bg-black/70 px-1.5 text-xs text-white">{a.duration ? `${Math.round(a.duration)} s` : "vidéo"}</span>}</div>
            <div className="space-y-1 p-2 text-xs"><div className="flex items-center justify-between gap-1"><Badge a={a} /><span className="truncate text-muted-foreground">{RIGHTS[a.rights]}</span></div>
              <div className="truncate">{a.event_title || "Sans événement"}</div><div className="truncate text-muted-foreground">{a.author_name}{a.author_handle ? ` @${a.author_handle}` : ""}</div></div>
          </div>))}</div>)}
      {edit && <MediaEdit a={edit} o={o} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />}
    </div>);
}

function Credits({ o }) {
  const [rows, setRows] = useState(null);
  const [h, setH] = useState({});
  const load = useCallback(() => api.get("/communication/credits").then((r) => setRows(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!rows) return <Loading />;
  return (
    <div className="space-y-4" data-testid="comm-credits">{!rows.length && <p className="card-soft p-6 text-sm text-muted-foreground">Aucun événement récent avec des intervenants.</p>}
      {rows.map((r) => (
        <div key={r.event.id} className="card-soft p-4" data-testid={`credits-event-${r.event.id}`}>
          <div className="mb-2 flex flex-wrap items-center gap-2"><Link className="font-semibold underline" to={`/evenements/${r.event.id}?tab=communication`}>{r.event.title}</Link><span className="text-xs text-muted-foreground">{fmtDate(r.event.start)}</span>
            {r.missing > 0 && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs text-amber-700" data-testid={`credits-missing-${r.event.id}`}>{r.missing} identifiant(s) manquant(s)</span>}<span className="flex-1" />
            <Button size="sm" variant="outline" onClick={() => copy(r.credit_text, "Crédits copiés")} data-testid={`credits-copy-${r.event.id}`}><Copy />Copier les crédits</Button></div>
          {r.credits.map((c) => (
            <div key={c.key} className="flex flex-wrap items-center gap-2 py-1 text-sm" data-testid={`credits-row-${c.key}`}><span className="w-44 text-muted-foreground">{c.role}</span><span className="w-56 truncate">{c.name}</span>
              {c.target && o.write ? <><span>@</span><Input className={`h-8 w-48 ${c.handle ? "" : "border-amber-500"}`} defaultValue={c.handle} onChange={(e) => setH({ ...h, [c.key]: e.target.value })} data-testid={`credits-handle-${c.key}`} />
                {h[c.key] != null && h[c.key] !== c.handle && <Button size="sm" variant="outline" onClick={() => api.put("/communication/handles", { kind: c.target.kind, id: c.target.id, handle: h[c.key] }).then(() => { toast.success("Identifiant enregistré sur la fiche"); load(); }).catch(ko)} data-testid={`credits-save-${c.key}`}>Enregistrer</Button>}</>
                : <span>{c.handle ? `@${c.handle}` : "—"}</span>}</div>))}
        </div>))}</div>);
}

function PostForm({ value, o, onClose, onSaved }) {
  const [f, setF] = useState({ ...value, hashtags: (value.hashtags || []).join(" ") });
  const [media, setMedia] = useState([]);
  const [props, setProps] = useState(null);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  useEffect(() => { api.get("/communication/media", { params: { event_id: f.event_id } }).then((r) => setMedia(r.data)).catch(ko); }, [f.event_id]);
  const body = () => { const { id, assets, ...b } = f; return { ...b, hashtags: f.hashtags.split(/[\s,]+/).filter(Boolean) }; };
  const save = () => (f.id ? api.put(`/communication/posts/${f.id}`, body()) : api.post("/communication/posts", body())).then(() => { toast.success("Publication enregistrée"); onSaved(); }).catch(ko);
  const ai = () => { setBusy(true); api.post("/communication/captions", { brand_id: f.brand_id, event_id: f.event_id, type: f.type, brief }).then((r) => setProps(r.data.proposals)).catch(ko).finally(() => setBusy(false)); };
  const fullText = `${f.caption_fr}\n\n${f.credits_text}\n\n${f.hashtags.split(/[\s,]+/).filter(Boolean).map((x) => `#${x}`).join(" ")}`.trim();
  return (
    <Dialog open onOpenChange={(x) => !x && onClose()}><DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto" data-testid="post-form">
      <DialogHeader><DialogTitle>{f.id ? "Modifier la publication" : "Nouvelle publication"}</DialogTitle><DialogDescription>Mode rappel manuel : à l'heure prévue, une tâche vous rappelle de publier depuis Instagram. La publication automatique viendra avec la connexion Meta.</DialogDescription></DialogHeader>
      <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground lg:grid-cols-4">
        <label className="col-span-2">Titre interne *<Input className="mt-1 h-9" value={f.title} onChange={set("title")} data-testid="post-title" /></label>
        <label>Marque *<select className={`${sel} mt-1 w-full`} value={f.brand_id} onChange={set("brand_id")} data-testid="post-brand"><option value="">—</option>{o.brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
        <label>Format<select className={`${sel} mt-1 w-full`} value={f.type} onChange={set("type")} data-testid="post-type">{Object.entries(TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label className="col-span-2">Événement<select className={`${sel} mt-1 w-full`} value={f.event_id} onChange={(e) => setF({ ...f, event_id: e.target.value, asset_ids: [] })} data-testid="post-event"><option value="">Tous les médias</option>{o.events.map((e) => <option key={e.id} value={e.id}>{e.title}</option>)}</select></label>
        <label>Date et heure<Input className="mt-1 h-9" type="datetime-local" value={f.scheduled_at} onChange={set("scheduled_at")} data-testid="post-scheduled" /></label>
        <label>Statut<select className={`${sel} mt-1 w-full`} value={f.status} onChange={set("status")} data-testid="post-status">{Object.entries(PST).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label></div>
      <div><div className="eyebrow mb-1">Médias ({f.asset_ids.length} choisi(s)) — seuls les médias « Publiable » peuvent être prêts ou planifiés</div>
        <div className="flex max-h-44 flex-wrap gap-2 overflow-y-auto" data-testid="post-media-picker">{!media.length && <span className="text-xs text-muted-foreground">Aucun média pour cette sélection.</span>}
          {media.map((a) => { const on = f.asset_ids.includes(a.id); return (
            <button key={a.id} title={a.blocked_reasons.join(" · ") || a.filename} onClick={() => setF({ ...f, asset_ids: on ? f.asset_ids.filter((x) => x !== a.id) : [...f.asset_ids, a.id] })} className={`relative rounded-lg border-2 ${on ? "border-primary" : "border-transparent"} ${a.status === "bloque" ? "opacity-50" : ""}`} data-testid={`post-media-${a.id}`}>
              <Thumb a={a} className="h-16 w-16 rounded-md object-cover" />{a.status === "bloque" && <span className="absolute inset-x-0 bottom-0 bg-red-600 text-[10px] text-white">bloqué</span>}</button>); })}</div></div>
      <div className="rounded-xl border border-border p-3"><div className="flex flex-wrap items-center gap-2"><Input className="h-9 flex-1" placeholder="Consigne pour l'assistant (facultatif) : angle, ambiance, détail à mettre en avant" value={brief} onChange={(e) => setBrief(e.target.value)} data-testid="post-brief" />
        <Button size="sm" variant="outline" disabled={busy || !f.brand_id || !o.ai} onClick={ai} data-testid="post-ai"><Sparkles />{busy ? "Rédaction…" : "3 propositions de légende"}</Button></div>
        {!o.ai && <p className="mt-1 text-xs text-muted-foreground">Assistant indisponible.</p>}
        {props && <div className="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-3" data-testid="post-proposals">{props.map((p, i) => (
          <button key={i} className="rounded-lg border border-border p-2 text-left text-xs hover:bg-secondary" onClick={() => setF({ ...f, caption_fr: p.fr, caption_en: p.en, hashtags: p.hashtags.join(" ") })} data-testid={`post-proposal-${i}`}><div className="line-clamp-6 whitespace-pre-wrap">{p.fr}</div><div className="mt-1 text-muted-foreground">Utiliser cette proposition (FR + EN)</div></button>))}</div>}</div>
      <div className="grid grid-cols-1 gap-3 text-xs text-muted-foreground lg:grid-cols-2">
        <label>Légende (français)<Textarea rows={5} className="mt-1" value={f.caption_fr} onChange={set("caption_fr")} data-testid="post-caption-fr" /></label>
        <label>Légende (anglais)<Textarea rows={5} className="mt-1" value={f.caption_en} onChange={set("caption_en")} data-testid="post-caption-en" /></label>
        <label>Crédits {f.event_id && <button type="button" className="underline" onClick={() => api.get(`/communication/events/${f.event_id}`).then((r) => setF((c) => ({ ...c, credits_text: r.data.credit_text }))).catch(ko)} data-testid="post-insert-credits">insérer ceux de l'événement</button>}
          <Textarea rows={4} className="mt-1" value={f.credits_text} onChange={set("credits_text")} data-testid="post-credits" /></label>
        <label>Hashtags (séparés par des espaces) {f.brand_id && <button type="button" className="underline" onClick={() => setF({ ...f, hashtags: (o.brands.find((b) => b.id === f.brand_id)?.hashtags || []).join(" ") })} data-testid="post-brand-hashtags">ceux de la marque</button>}
          <Textarea rows={4} className="mt-1" value={f.hashtags} onChange={set("hashtags")} data-testid="post-hashtags" /></label>
        {f.status === "publie" && <label className="lg:col-span-2">Lien de la publication (https://…)<Input className="mt-1 h-9" value={f.permalink} onChange={set("permalink")} data-testid="post-permalink" /></label>}</div>
      <div className="flex justify-between"><Button variant="outline" onClick={() => copy(fullText, "Légende, crédits et hashtags copiés")} data-testid="post-copy"><Copy />Copier pour Instagram</Button>
        <div className="flex gap-2"><Button variant="ghost" onClick={onClose}>Annuler</Button><Button disabled={!f.title.trim() || !f.brand_id} onClick={save} data-testid="post-save">Enregistrer</Button></div></div>
    </DialogContent></Dialog>);
}

function Posts({ o, calendar }) {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(null);
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const load = useCallback(() => api.get("/communication/posts").then((r) => setRows(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!rows) return <Loading />;
  const brand = (id) => o.brands.find((b) => b.id === id)?.name || "";
  const move = (n) => { const d = new Date(`${month}-01T12:00`); d.setMonth(d.getMonth() + n); setMonth(d.toISOString().slice(0, 7)); };
  const first = new Date(`${month}-01T12:00`);
  const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const cells = [...Array((first.getDay() + 6) % 7).fill(null), ...Array.from({ length: days }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`)];
  const Card = ({ p, small }) => (
    <button className={`w-full rounded-lg border border-border bg-card text-left ${small ? "p-1 text-[11px]" : "p-3 text-sm"}`} onClick={() => setForm(p)} data-testid={`post-card-${p.id}`}>
      <div className="flex items-center gap-2">{!small && p.assets[0] && <Thumb a={p.assets[0]} className="h-12 w-12 rounded-md object-cover" />}<div className="min-w-0 flex-1"><div className="truncate font-medium">{small ? `${p.scheduled_at.slice(11, 16)} ` : ""}{p.title}</div>
        {!small && <div className="text-xs text-muted-foreground">{brand(p.brand_id)} · {TYPES[p.type]} · {p.scheduled_at ? `${fmtDate(p.scheduled_at.slice(0, 10))} ${p.scheduled_at.slice(11, 16)}` : "non daté"}</div>}</div>
        <span className="rounded-full bg-secondary px-2 py-0.5 text-xs" data-testid={`post-status-${p.id}`}>{PST[p.status]}</span></div></button>);
  return (
    <div data-testid={calendar ? "comm-calendar" : "comm-studio"}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {calendar && <><Button size="icon" variant="outline" onClick={() => move(-1)} data-testid="calendar-prev"><ChevronLeft /></Button><b className="w-40 text-center capitalize" data-testid="calendar-month">{first.toLocaleDateString("fr-FR", { month: "long", year: "numeric" })}</b><Button size="icon" variant="outline" onClick={() => move(1)} data-testid="calendar-next"><ChevronRight /></Button></>}
        <span className="rounded-full bg-secondary px-3 py-1 text-xs" data-testid="publish-mode">Publication : rappel manuel</span>
        {o.connectors.map((c) => <span key={c.key} className="rounded-full border border-dashed border-border px-3 py-1 text-xs text-muted-foreground" data-testid={`connector-${c.key}`}>{c.label} : non connecté</span>)}<span className="flex-1" />
        {o.write && <Button onClick={() => setForm({ ...POST, brand_id: o.brands[0].id })} data-testid="post-new"><Plus />Publication</Button>}</div>
      {calendar ? (
        <div className="grid grid-cols-7 gap-1" data-testid="calendar-grid">{["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((x) => <div key={x} className="text-center text-xs text-muted-foreground">{x}</div>)}
          {cells.map((day, i) => <div key={day || `e${i}`} className={`min-h-24 rounded-lg border border-border p-1 ${day ? "bg-card" : "border-transparent"}`} data-testid={day ? `calendar-day-${day}` : undefined}>
            {day && <><button className="text-xs text-muted-foreground" onClick={() => o.write && setForm({ ...POST, brand_id: o.brands[0].id, scheduled_at: `${day}T18:00` })}>{Number(day.slice(8))}</button>
              <div className="space-y-1">{rows.filter((p) => p.scheduled_at.slice(0, 10) === day).map((p) => <Card key={p.id} p={p} small />)}</div></>}</div>)}</div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5" data-testid="studio-board">{Object.entries(PST).map(([k, l]) => (
          <div key={k} data-testid={`studio-col-${k}`}><div className="eyebrow mb-2">{l} ({rows.filter((p) => p.status === k).length})</div><div className="space-y-2">{rows.filter((p) => p.status === k).map((p) => <Card key={p.id} p={p} />)}</div></div>))}</div>)}
      {form && <PostForm value={form} o={o} onClose={() => setForm(null)} onSaved={() => { setForm(null); load(); }} />}
    </div>);
}

function Settings({ o, reload }) {
  const [f, setF] = useState({ brands: o.brands.map((b) => ({ ...b, hashtags: b.hashtags.join(" ") })), reminder_days: o.reminder_days.join(", "), request_message: o.request_message });
  const setB = (i, p) => setF({ ...f, brands: f.brands.map((b, j) => (j === i ? { ...b, ...p } : b)) });
  const save = () => api.put("/communication/settings", { brands: f.brands.map((b) => ({ id: b.id, handle: b.handle, hashtags: b.hashtags.split(/[\s,]+/).filter(Boolean) })), reminder_days: f.reminder_days.split(/[\s,]+/).map(Number).filter(Boolean), request_message: f.request_message }).then(() => { toast.success("Réglages enregistrés"); reload(); }).catch(ko);
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2" data-testid="comm-settings">
      <div className="card-soft p-4"><div className="eyebrow mb-2">Marques</div>
        {f.brands.map((b, i) => <div key={b.id} className="mb-3" data-testid={`brand-${b.id}`}><div className="font-semibold">{b.name}</div>
          <div className="mt-1 flex items-center gap-1 text-sm"><span>@</span><Input className="h-9" disabled={!o.write} placeholder="compte Instagram" value={b.handle} onChange={(e) => setB(i, { handle: e.target.value })} data-testid={`brand-handle-${b.id}`} /></div>
          <Input className="mt-1 h-9" disabled={!o.write} placeholder="hashtags habituels, séparés par des espaces" value={b.hashtags} onChange={(e) => setB(i, { hashtags: e.target.value })} data-testid={`brand-hashtags-${b.id}`} /></div>)}</div>
      <div className="space-y-4"><div className="card-soft p-4"><div className="eyebrow mb-2">Collectes</div>
        <label className="text-xs text-muted-foreground">Relances après l'événement (jours)<Input className="mt-1 h-9" disabled={!o.write} value={f.reminder_days} onChange={(e) => setF({ ...f, reminder_days: e.target.value })} data-testid="settings-reminder-days" /></label>
        <label className="mt-2 block text-xs text-muted-foreground">Message de la demande<Textarea rows={4} className="mt-1" disabled={!o.write} value={f.request_message} onChange={(e) => setF({ ...f, request_message: e.target.value })} data-testid="settings-message" /></label></div>
        <div className="card-soft p-4"><div className="eyebrow mb-2">Connexions</div>{o.connectors.map((c) => <div key={c.key} className="flex justify-between py-1 text-sm" data-testid={`settings-connector-${c.key}`}><span>{c.label}</span><span className="text-muted-foreground">non connecté</span></div>)}
          <div className="flex justify-between py-1 text-sm"><span>Vidéo (ffmpeg)</span><span data-testid="settings-ffmpeg">{o.video ? "disponible" : "absent"}</span></div></div>
        {o.write && <div className="flex justify-end"><Button onClick={save} data-testid="settings-save">Enregistrer</Button></div>}</div>
    </div>);
}

export default function Communication() {
  const [sp, setSp] = useSearchParams();
  const [o, setO] = useState(null);
  const tab = sp.get("tab") || "media";
  const load = useCallback(() => api.get("/communication/overview").then((r) => setO(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!o) return <Loading />;
  return (
    <div data-testid="communication-page">
      <PageHeader eyebrow="Communication" title="Communication" subtitle={`${o.counts.media} média(s) · ${o.counts.requests_open} collecte(s) en cours · ${o.counts.posts_planned} publication(s) planifiée(s)`} />
      <div className="mb-4 flex flex-wrap gap-2" data-testid="comm-tabs">{TABS.map(([k, l]) => <button key={k} onClick={() => setSp({ tab: k })} data-testid={`comm-tab-${k}`} className={`h-9 rounded-full border px-4 text-sm font-medium ${tab === k ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`}>{l}</button>)}</div>
      {tab === "media" && <Media o={o} initialEvent={sp.get("event")} />}
      {tab === "collectes" && <Requests events={o.events} write={o.write} sending={o.sending} />}
      {tab === "credits" && <Credits o={o} />}
      {tab === "studio" && <Posts o={o} />}
      {tab === "calendrier" && <Posts o={o} calendar />}
      {tab === "reglages" && <Settings o={o} reload={load} />}
    </div>);
}
