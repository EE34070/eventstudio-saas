import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, errMsg } from "@/lib/api";
import { Pill, useSelection } from "@/components/dj/Conflicts";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const ST = { option_requested: "Option demandée", option_accepted: "Option acceptée", option_refused: "Option refusée", option_conditions: "Sous conditions", confirmed: "Confirmée", acknowledged: "Accusé reçu", done: "Réalisée", invoiced: "Facturée", paid: "Payée", option_lifted: "Option levée", cancelled: "Annulée" };
const OPEN = ["option_requested", "option_accepted", "option_conditions"];

export default function DjBlock({ eid }) {
  const [d, setD] = useState(null);
  const [inact, setInact] = useState(false);
  const [c, setC] = useState(null);
  const [m, setM] = useState(null);
  const [pick, setPick] = useState([]);
  const [o, setO] = useState({ proposed_fee: "", start_time: "19:00", end_time: "02:00" });
  const [cf, setCf] = useState(null);
  const [sel] = useSelection(eid);
  const load = useCallback(() => api.get(`/events/${eid}/dj`).then((r) => { setD(r.data); setC((x) => x || { ...r.data.criteria, languages: r.data.criteria.languages.join(", "), genres_love: r.data.criteria.genres_love.join(", "), genres_avoid: r.data.criteria.genres_avoid.join(", ") }); }).catch(() => setD(false)), [eid]);
  useEffect(() => { load(); }, [load]);
  if (!d || !c) return null;
  const list = (s) => s.split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
  const find = () => api.put(`/events/${eid}/dj/criteria`, { ...c, languages: list(c.languages), genres_love: list(c.genres_love), genres_avoid: list(c.genres_avoid), prefilled: undefined }).then(() => api.get(`/events/${eid}/dj/match`, { params: { inactive: inact } })).then((r) => setM(r.data)).catch(ko);
  const act = (b, a, body = {}) => api.post(`/dj/bookings/${b}/${a}`, body).then(() => { setCf(null); load(); }).catch(ko);
  const options = () => api.post(`/events/${eid}/dj/options`, { ...o, proposed_fee: Number(o.proposed_fee) || 0, provider_ids: pick }).then(() => { toast.success("Option(s) posée(s)"); setPick([]); load(); }).catch(ko);
  const Row = ({ r, out }) => (
    <div className="rounded-xl border border-border p-2" data-testid={`dj-match-${r.provider_id}`}><label className="flex flex-wrap items-center gap-2 font-semibold">{!out && <input type="checkbox" checked={pick.includes(r.provider_id)} onChange={(e) => setPick(e.target.checked ? [...pick, r.provider_id].slice(0, 3) : pick.filter((p) => p !== r.provider_id))} data-testid={`dj-match-pick-${r.provider_id}`} />}{r.name}<span className="rounded-full bg-secondary px-2 text-xs" data-testid={`dj-match-score-${r.provider_id}`}>{r.score} %</span><Pill row={sel?.by[r.provider_id]} /><span className="text-xs font-normal text-muted-foreground">{r.base_rate} € · {r.state}</span></label>
      <p className="text-xs text-muted-foreground">{out ? r.excluded.join(" ; ") : r.lines.map((l) => `${l.why} (${l.points}/${l.max})`).join(" · ")}</p></div>);
  return (
    <div className="mt-6 space-y-3 rounded-2xl border border-border p-4 text-sm" data-testid="event-dj-block"><h3 className="text-lg font-bold">DJ</h3>
      {d.banner && <div className="flex flex-wrap items-center gap-3 rounded-xl bg-blue-500/10 p-3 font-semibold" data-testid="dj-banner">{d.banner.text}
        {d.banner.kind === "confirm" ? <Button size="sm" onClick={() => api.get(`/dj/bookings/${d.banner.booking_id}/confirmation-draft`).then((r) => setCf({ id: d.banner.booking_id, ...r.data })).catch(ko)} data-testid="dj-banner-confirm">Confirmer la prestation</Button>
          : <Button size="sm" variant="outline" onClick={() => Promise.all(d.bookings.filter((b) => OPEN.includes(b.status)).map((b) => api.post(`/dj/bookings/${b.id}/lift`, {}))).then(load).catch(ko)} data-testid="dj-banner-lift">Lever les options</Button>}</div>}
      {cf && <div className="space-y-2 rounded-xl border border-border p-3" data-testid="dj-confirm-panel"><b>E-mail de confirmation à {cf.to || "(pas d'e-mail)"}</b><Input value={cf.subject} onChange={(e) => setCf({ ...cf, subject: e.target.value })} data-testid="dj-confirm-subject" />
        <textarea className="w-full rounded-xl border border-border bg-background p-2" rows={10} value={cf.body} onChange={(e) => setCf({ ...cf, body: e.target.value })} data-testid="dj-confirm-body" />
        <div className="flex gap-2"><Button size="sm" onClick={() => act(cf.id, "confirm", { subject: cf.subject, body: cf.body })} data-testid="dj-confirm-send">Confirmer et envoyer</Button><Button size="sm" variant="outline" onClick={() => setCf(null)}>Annuler</Button></div></div>}
      {d.bookings.map((b) => <div key={b.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-border p-2" data-testid={`dj-booking-${b.id}`}><b>{b.preference_rank}. {b.provider_name}</b><span className="rounded-full bg-secondary px-2 text-xs" data-testid={`dj-booking-status-${b.id}`}>{ST[b.status]}</span><span>{b.proposed_fee} € · {b.start_time}–{b.end_time}{OPEN.includes(b.status) ? ` · expire le ${b.option_expires_at}` : ""}{b.dj_comment ? ` · « ${b.dj_comment} »` : ""}</span><span className="ml-auto" />
        {OPEN.includes(b.status) && <><Button size="sm" onClick={() => api.get(`/dj/bookings/${b.id}/confirmation-draft`).then((r) => setCf({ id: b.id, ...r.data })).catch(ko)} data-testid={`dj-booking-confirm-${b.id}`}>Confirmer</Button><Button size="sm" variant="outline" onClick={() => act(b.id, "extend", { days: 7 })} data-testid={`dj-booking-extend-${b.id}`}>+7 j</Button><Button size="sm" variant="outline" onClick={() => act(b.id, "lift")} data-testid={`dj-booking-lift-${b.id}`}>Lever</Button></>}
        {["confirmed", "acknowledged"].includes(b.status) && <Button size="sm" variant="destructive" onClick={() => { const reason = window.prompt("Motif de l'annulation"); if (reason) act(b.id, "cancel", { reason }); }} data-testid={`dj-booking-cancel-${b.id}`}>Annuler</Button>}</div>)}
      <div className="space-y-2 rounded-xl bg-secondary/40 p-3" data-testid="dj-criteria"><b>Vibe recherchée{d.criteria.prefilled ? " (pré-remplie depuis le client et Ma musique)" : ""}</b>
        <div className="flex flex-wrap gap-2"><Input className="w-40" placeholder="Langues (fr, en)" value={c.languages} onChange={(e) => setC({ ...c, languages: e.target.value })} data-testid="dj-criteria-languages" />
          <select className={sel} value={c.animation_style} onChange={(e) => setC({ ...c, animation_style: e.target.value })} data-testid="dj-criteria-style"><option value="">Style d'animation</option><option value="discreet">Discret</option><option value="balanced">Équilibré</option><option value="mc">Animateur-MC</option></select>
          <select className={sel} value={c.tier} onChange={(e) => setC({ ...c, tier: e.target.value })} data-testid="dj-criteria-tier"><option value="">Niveau visé</option><option value="signature">Signature</option><option value="premium">Premium</option><option value="standard">Standard</option></select>
          <Input className="w-56" placeholder={`J'adore (${Object.keys(d.genres).slice(0, 3).join(", ")}…)`} value={c.genres_love} onChange={(e) => setC({ ...c, genres_love: e.target.value })} data-testid="dj-criteria-love" /><Input className="w-44" placeholder="À éviter" value={c.genres_avoid} onChange={(e) => setC({ ...c, genres_avoid: e.target.value })} data-testid="dj-criteria-avoid" /></div>
        <div className="flex flex-wrap gap-3">{d.vibes.map((v) => <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={c.vibe_tags.includes(v)} onChange={(e) => setC({ ...c, vibe_tags: e.target.checked ? [...c.vibe_tags, v] : c.vibe_tags.filter((t) => t !== v) })} data-testid={`dj-criteria-vibe-${v}`} />{v}</label>)}</div>
        <Button size="sm" onClick={find} data-testid="dj-find">Trouver le DJ</Button></div>
      <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={inact} onChange={(e) => setInact(e.target.checked)} data-testid="dj-match-inactive" />Afficher aussi les inactifs (prochaine recherche)</label>
      {m && <div className="space-y-2" data-testid="dj-matches">{m.matches.length === 0 && <p>Aucun DJ ne correspond le {m.date}.</p>}{m.matches.map((r) => <Row key={r.provider_id} r={r} />)}
        {pick.length > 0 && <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border p-2" data-testid="dj-pick-actions">Cachet <Input type="number" className="w-24" value={o.proposed_fee} onChange={(e) => setO({ ...o, proposed_fee: e.target.value })} data-testid="dj-option-fee" /><Input type="time" className="w-28" value={o.start_time} onChange={(e) => setO({ ...o, start_time: e.target.value })} data-testid="dj-option-start" /><Input type="time" className="w-28" value={o.end_time} onChange={(e) => setO({ ...o, end_time: e.target.value })} data-testid="dj-option-end" />
          <Button size="sm" onClick={options} data-testid="dj-option-submit">Poser une option ({pick.length})</Button><Button size="sm" variant="outline" onClick={() => api.put(`/events/${eid}/dj/shortlist`, { provider_ids: pick }).then(() => { toast.success("Proposés au client dans son espace, sans prix"); load(); }).catch(ko)} data-testid="dj-shortlist-submit">Proposer au client</Button></div>}
        {m.excluded.length > 0 && <details data-testid="dj-excluded"><summary className="cursor-pointer text-xs">Hors critères ({m.excluded.length})</summary><div className="mt-2 space-y-2">{m.excluded.map((r) => <Row key={r.provider_id} r={r} out />)}</div></details>}</div>}
      {d.shortlist.provider_ids.length > 0 && <p className="text-xs" data-testid="dj-shortlist-state">{d.shortlist.provider_ids.length} DJ proposé(s) au client{d.shortlist.preferred_id ? ` — préférence indiquée : ${d.bookings.find((b) => b.provider_id === d.shortlist.preferred_id)?.provider_name || m?.matches.find((r) => r.provider_id === d.shortlist.preferred_id)?.name || "voir Mes DJ"}` : " — pas encore de préférence"}</p>}
      {d.log.length > 0 && <details data-testid="dj-log"><summary className="cursor-pointer text-xs">Journal ({d.log.length}) et messages ({d.messages.length}, non envoyés hors production)</summary><div className="mt-1 text-xs text-muted-foreground">{d.log.map((l) => <div key={l.id}>{l.at.slice(0, 16).replace("T", " ")} · {ST[l.action] || l.action} · {l.by} {l.detail}</div>)}</div></details>}
    </div>
  );
}
