import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { DjPlanning } from "@/components/dj/DjPlanning";
import { DJ_COLORS } from "@/portal/Dj";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const LABEL = { available: "Disponible", available_default: "Disponible (par défaut)", maybe: "À confirmer", unknown: "Inconnu", unavailable: "Indisponible", option: "Option", confirmed: "Confirmé" };
const add = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };

function Grid() {
  const [start, setStart] = useState(new Date().toISOString().slice(0, 10));
  const [we, setWe] = useState(true);
  const [d, setD] = useState(null);
  const [date, setDate] = useState("");
  const [all, setAll] = useState(false);
  const [found, setFound] = useState(null);
  const [inactive, setInactive] = useState(false);
  useEffect(() => { api.get("/dj/availability", { params: { start, end: add(start, 62), inactive } }).then((r) => setD(r.data)).catch(ko); }, [start, inactive]);
  useEffect(() => { if (date) api.get("/dj/search", { params: { date, all, inactive } }).then((r) => setFound(r.data)).catch(ko); }, [date, all, inactive]);
  const days = Array.from({ length: 63 }, (_, i) => add(start, i)).filter((x) => !we || [0, 5, 6].includes(new Date(x).getDay()));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border p-3 text-sm" data-testid="dj-search"><b>Qui est disponible le</b><Input type="date" className="w-44" value={date} onChange={(e) => setDate(e.target.value)} data-testid="dj-search-date" />
        <label className="flex items-center gap-1"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} data-testid="dj-search-all" />Afficher tout</label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} data-testid="dj-show-inactive" />Afficher aussi les inactifs</label>
        {found && <div className="flex w-full flex-wrap gap-2" data-testid="dj-search-results">{found.length === 0 ? "Aucun DJ." : found.map((x) => <span key={x.provider_id} className={`rounded-full px-3 py-1 text-xs ${DJ_COLORS[x.state]}`}>{x.name} · {LABEL[x.state]}{x.stale ? " · calendrier ancien" : ""}</span>)}</div>}</div>
      <div className="flex flex-wrap items-center gap-3 text-sm"><Input type="date" className="w-44" value={start} onChange={(e) => setStart(e.target.value)} data-testid="dj-grid-start" /><label className="flex items-center gap-1"><input type="checkbox" checked={we} onChange={(e) => setWe(e.target.checked)} data-testid="dj-grid-weekends" />Week-ends seulement</label>
        {Object.entries(LABEL).map(([k, l]) => <span key={k} className={`rounded px-2 py-0.5 text-xs ${DJ_COLORS[k]}`}>{l}</span>)}</div>
      <div className="overflow-x-auto rounded-2xl border border-border"><table className="text-xs" data-testid="dj-grid"><thead><tr><th className="sticky left-0 bg-card p-2 text-left">DJ</th>{days.map((x) => <th key={x} className="px-1 py-2 font-normal">{x.slice(8)}/{x.slice(5, 7)}</th>)}</tr></thead>
        <tbody>{(d?.djs || []).map((r) => <tr key={r.provider_id} className="border-t border-border" data-testid={`dj-grid-row-${r.provider_id}`}><td className="sticky left-0 whitespace-nowrap bg-card p-2 font-semibold">{r.name}{r.stale && <span className="ml-1 rounded bg-amber-500/20 px-1 text-amber-700" title="Calendrier non mis à jour depuis plus de 30 jours">!</span>}</td>
          {days.map((x) => { const s = r.days[x]?.state || (r.default_state === "available" ? "available_default" : "unknown"); return <td key={x} className="p-0.5"><div className={`h-6 w-8 rounded ${DJ_COLORS[s]}`} title={`${LABEL[s]}${r.days[x]?.from_time ? ` dès ${r.days[x].from_time}` : ""}`} data-testid={`dj-cell-${r.provider_id}-${x}`} data-state={s} /></td>; })}</tr>)}</tbody></table></div>
    </div>
  );
}

function Djs() {
  const [d, setD] = useState(null);
  const [f, setF] = useState({ vibe: "", tier: "", status: "", lang: "" });
  const [ed, setEd] = useState(null);
  const load = useCallback(() => api.get("/dj/profiles").then((r) => setD(r.data)).catch(ko), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return null;
  const rows = d.djs.filter((x) => (!f.vibe || (x.vibe_tags || []).includes(f.vibe)) && (!f.tier || x.tier === f.tier) && (!f.status || x.dj_status === f.status) && (!f.lang || (x.mc_languages || []).some((l) => l.lang === f.lang && l.level !== "basic")));
  const save = () => api.put(`/dj/profiles/${ed.provider_id}`, { vibe_tags: ed.vibe_tags || [], animation_style: ed.animation_style || "", tier: ed.tier || "", internal_rating: Number(ed.internal_rating) || 0, internal_notes: ed.internal_notes || "", dj_status: ed.dj_status || "active" }).then(() => { toast.success("Fiche DJ enregistrée"); setEd(null); load(); }).catch(ko);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" data-testid="dj-filters">
        <select className={sel} value={f.vibe} onChange={(e) => setF({ ...f, vibe: e.target.value })} data-testid="dj-filter-vibe"><option value="">Toutes les vibes</option>{d.vibes.map((v) => <option key={v}>{v}</option>)}</select>
        <select className={sel} value={f.tier} onChange={(e) => setF({ ...f, tier: e.target.value })} data-testid="dj-filter-tier"><option value="">Tous niveaux</option><option value="signature">Signature</option><option value="premium">Premium</option><option value="standard">Standard</option></select>
        <select className={sel} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} data-testid="dj-filter-status"><option value="">Tous statuts</option><option value="active">Actif</option><option value="trial">En test</option><option value="blocked">Ne plus solliciter</option></select>
        <Input className="w-40" placeholder="Langue (fr, en…)" value={f.lang} onChange={(e) => setF({ ...f, lang: e.target.value.toLowerCase() })} data-testid="dj-filter-lang" /></div>
      <table className="w-full text-sm" data-testid="dj-list"><thead><tr className="text-left text-xs text-muted-foreground"><th className="p-2">DJ</th><th>Langues</th><th>Vibe</th><th>Niveau</th><th>Note</th><th>Missions</th><th>Réponses</th><th /></tr></thead>
        <tbody>{rows.map((x) => <tr key={x.provider_id} className="border-t border-border" data-testid={`dj-row-${x.provider_id}`}><td className="p-2 font-semibold">{x.name}</td><td>{(x.mc_languages || []).map((l) => l.lang.toUpperCase()).join(" ")}</td><td>{(x.vibe_tags || []).join(", ")}</td><td>{x.tier || "—"}</td><td>{x.internal_rating || "—"}</td><td>{x.missions}</td><td>{x.reply_rate == null ? "—" : `${Math.round(x.reply_rate * 100)} %`}</td>
          <td><Button size="sm" variant="ghost" onClick={() => setEd(x)} data-testid={`dj-edit-${x.provider_id}`}>Classer</Button></td></tr>)}</tbody></table>
      {ed && <div className="space-y-2 rounded-2xl border border-border p-4 text-sm" data-testid="dj-edit-panel"><b>{ed.name} — critères privés (jamais visibles du DJ)</b>
        <div className="flex flex-wrap gap-3">{d.vibes.map((v) => <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={(ed.vibe_tags || []).includes(v)} onChange={(e) => setEd({ ...ed, vibe_tags: e.target.checked ? [...(ed.vibe_tags || []), v] : ed.vibe_tags.filter((t) => t !== v) })} data-testid={`dj-vibe-${v}`} />{v}</label>)}</div>
        <div className="flex flex-wrap gap-2">
          <select className={sel} value={ed.animation_style || ""} onChange={(e) => setEd({ ...ed, animation_style: e.target.value })} data-testid="dj-edit-style"><option value="">Style d'animation</option><option value="discreet">Discret</option><option value="balanced">Équilibré</option><option value="mc">Animateur-MC</option></select>
          <select className={sel} value={ed.tier || ""} onChange={(e) => setEd({ ...ed, tier: e.target.value })} data-testid="dj-edit-tier"><option value="">Niveau</option><option value="signature">Signature</option><option value="premium">Premium</option><option value="standard">Standard</option></select>
          <select className={sel} value={ed.internal_rating || 0} onChange={(e) => setEd({ ...ed, internal_rating: e.target.value })} data-testid="dj-edit-rating">{[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n ? `Note ${n}/5` : "Note"}</option>)}</select>
          <select className={sel} value={ed.dj_status || "active"} onChange={(e) => setEd({ ...ed, dj_status: e.target.value })} data-testid="dj-edit-status"><option value="active">Actif</option><option value="trial">En test</option><option value="blocked">Ne plus solliciter</option></select></div>
        <textarea className="w-full rounded-xl border border-border bg-background p-2" rows={2} placeholder="Notes internes" value={ed.internal_notes || ""} onChange={(e) => setEd({ ...ed, internal_notes: e.target.value })} data-testid="dj-edit-notes" />
        <div className="flex gap-2"><Button size="sm" onClick={save} data-testid="dj-edit-save">Enregistrer</Button><Button size="sm" variant="outline" onClick={() => setEd(null)}>Fermer</Button></div></div>}
    </div>
  );
}

function Invoices() {
  const [rows, setRows] = useState([]);
  const [st, setSt] = useState("");
  const load = useCallback(() => api.get("/dj/invoices", { params: { status: st } }).then((r) => setRows(r.data)).catch(ko), [st]);
  useEffect(() => { load(); }, [load]);
  const act = (i, a) => { const reason = a === "refuse" ? window.prompt("Motif du refus") : ""; if (reason !== null) api.post(`/dj/invoices/${i.id}/${a}`, { reason }).then(load).catch(ko); };
  const open = (i) => api.get(`/files/${i.file.slice(5)}`, { responseType: "blob" }).then((r) => window.open(URL.createObjectURL(r.data))).catch(ko);
  const csv = () => api.get("/dj/invoices/export", { responseType: "blob" }).then((r) => { const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = "factures-dj.csv"; a.click(); }).catch(ko);
  return (
    <div className="space-y-3"><div className="flex gap-2"><select className={sel} value={st} onChange={(e) => setSt(e.target.value)} data-testid="dj-invoices-status"><option value="">Toutes</option><option value="to_check">À vérifier</option><option value="validated">Validée</option><option value="paid">Payée</option><option value="refused">Refusée</option></select><Button size="sm" variant="outline" onClick={csv} data-testid="dj-invoices-export">Export CSV</Button></div>
      {rows.length === 0 && <p className="text-sm text-muted-foreground">Aucune facture.</p>}
      {rows.map((i) => <div key={i.id} className="rounded-2xl border border-border p-3 text-sm" data-testid={`dj-invoice-${i.id}`}>
        <div className="flex flex-wrap items-center gap-3"><b>{i.provider_name}</b><span>n° {i.number || "—"} · {i.total_ht} € HT (prévu {i.expected_ht} €) · prestation du {i.service_date}</span>
          <span className={`rounded-full px-2 py-0.5 text-xs ${i.match_status === "conform" ? "bg-emerald-50 text-emerald-700" : "bg-amber-500/20 text-amber-700"}`} data-testid={`dj-invoice-match-${i.id}`}>{i.match_status === "conform" ? "Conforme" : i.match_status === "mismatch" ? "Écart" : "À vérifier à la main"}</span><span className="rounded-full bg-secondary px-2 py-0.5 text-xs">{i.status}</span><span className="ml-auto" />
          <Button size="sm" variant="ghost" onClick={() => open(i)}>Voir le PDF</Button>
          {i.status === "to_check" && <><Button size="sm" onClick={() => act(i, "validate")} data-testid={`dj-invoice-validate-${i.id}`}>Valider</Button><Button size="sm" variant="outline" onClick={() => act(i, "refuse")} data-testid={`dj-invoice-refuse-${i.id}`}>Refuser</Button></>}
          {i.status === "validated" && <Button size="sm" onClick={() => act(i, "paid")} data-testid={`dj-invoice-paid-${i.id}`}>Marquer payée</Button>}</div>
        {i.mismatch_reasons?.length > 0 && <p className="mt-1 text-xs text-amber-700">{i.mismatch_reasons.join(" ; ")}</p>}</div>)}
    </div>
  );
}

export default function DjAdmin() {
  const [tab, setTab] = useState(new URLSearchParams(window.location.search).get("tab") || "planning");
  return (
    <div className="space-y-6" data-testid="dj-admin-page"><h1 className="text-4xl font-bold">DJ partenaires</h1>
      <div className="flex gap-2">{[["planning", "Planning DJ"], ["grid", "Disponibilités"], ["djs", "Mes DJ"], ["invoices", "Factures DJ"]].map(([k, l]) => <Button key={k} size="sm" variant={tab === k ? "default" : "outline"} onClick={() => setTab(k)} data-testid={`dj-admin-tab-${k}`}>{l}</Button>)}</div>
      {tab === "planning" ? <DjPlanning /> : tab === "grid" ? <Grid /> : tab === "djs" ? <Djs /> : <Invoices />}
    </div>
  );
}
