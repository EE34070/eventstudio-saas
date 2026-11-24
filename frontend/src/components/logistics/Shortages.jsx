import { useCallback, useEffect, useState } from "react";
import { Offers } from "@/components/catalogue/Suppliers";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AlertTriangle, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Section, Loading, EmptyState } from "@/components/common";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { fmtDate } from "@/lib/constants";

const ko = (e) => toast.error(errMsg(e));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-xs";
export const SH_STATUS = { a_traiter: "À traiter", solution: "Solution choisie", resolu: "Résolu" };
const TONE = { a_traiter: "bg-red-500/10 text-red-700", solution: "bg-amber-500/10 text-amber-700", resolu: "bg-emerald-500/10 text-emerald-700" };
const R_STATUS = { envoyee: "En attente de réponse", repondue: "Réponse reçue", acceptee: "Acceptée", non_retenue: "Non retenue" };
const Badge = ({ s, id }) => <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${TONE[s]}`} data-testid={`shortage-status-${id}`}>{SH_STATUS[s]}</span>;
const dates = (l) => `${fmtDate(l.date_from)} → ${fmtDate(l.date_to)}`;

function Line({ l, write, solutions, equipment, onDone }) {
  const [f, setF] = useState({ solution_type: "", warehouse_id: "", substitute_id: "", note: "" });
  const patch = (body) => api.patch(`/shortages/${l.id}`, body).then((r) => { if (r.data.warning) toast.warning(r.data.warning, { duration: 9000 }); else toast.success("Manque mis à jour"); setF({ solution_type: "", warehouse_id: "", substitute_id: "", note: "" }); onDone(); }).catch(ko);
  const ready = f.solution_type && (f.solution_type !== "transfert" || f.warehouse_id) && (f.solution_type !== "substitution" || f.substitute_id);
  const sol = l.solution;
  return (
    <div className="rounded-xl border border-border p-3 text-sm" data-testid={`shortage-line-${l.product_id}`}>
      <div className="flex flex-wrap items-center gap-2"><b>{l.ref} {l.name}</b><Badge s={l.status} id={l.product_id} />
        <span className="ml-auto text-xs text-muted-foreground">{dates(l)}</span></div>
      <div className="mt-1 text-xs text-muted-foreground">Demandé <b className="text-foreground">{l.requested}</b> · disponible aux dates <b className="text-foreground">{l.available}</b> ({l.by_warehouse.map((w) => `${w.name} : ${w.qty}`).join(", ") || "aucun entrepôt utilisable"}) · manquant <b className="text-red-600" data-testid={`shortage-missing-${l.product_id}`}>{l.missing} {l.stock_uom && l.stock_uom !== "piece" ? l.stock_uom : l.missing > 1 ? "pièces" : "pièce"}{l.secondary_uom && l.missing_secondary ? ` / ${l.missing_secondary} ${l.secondary_uom}` : ""}</b> · origine : {l.origin}</div>
      {sol && <div className="mt-1 text-xs" data-testid={`shortage-solution-${l.product_id}`}>Solution : <b>{sol.label}</b>{sol.warehouse_name ? ` (${sol.warehouse_name})` : ""}{sol.substitute_name ? ` → ${sol.substitute_name}` : ""}{sol.qty != null ? ` · ${sol.qty}` : ""}{sol.note ? ` · ${sol.note}` : ""}{sol.purchase_id ? <> · <Link className="underline" to="/a-acheter">voir dans À acheter</Link></> : null} — {sol.by}</div>}
      <Offers offers={l.offers} testid={`shortage-offers-${l.product_id}`} />
      {write && <div className="mt-2 flex flex-wrap items-center gap-2">
        <select className={sel} value={f.solution_type} onChange={(e) => setF({ ...f, solution_type: e.target.value })} data-testid={`shortage-solution-select-${l.product_id}`}><option value="">Choisir une solution…</option>{Object.entries(solutions).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        {f.solution_type === "transfert" && <select className={sel} value={f.warehouse_id} onChange={(e) => setF({ ...f, warehouse_id: e.target.value })} data-testid={`shortage-warehouse-${l.product_id}`}><option value="">Entrepôt source…</option>{l.by_warehouse.map((w) => <option key={w.warehouse_id} value={w.warehouse_id}>{w.name} ({w.qty} dispo)</option>)}</select>}
        {f.solution_type === "substitution" && <select className={sel} value={f.substitute_id} onChange={(e) => setF({ ...f, substitute_id: e.target.value })} data-testid={`shortage-substitute-${l.product_id}`}><option value="">Produit de remplacement…</option>{equipment.filter((x) => x.id !== l.product_id).map((x) => <option key={x.id} value={x.id}>{x.ref} {x.name}</option>)}</select>}
        {f.solution_type && <Input className="h-9 w-52 text-xs" placeholder="Note (optionnel)" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} data-testid={`shortage-note-${l.product_id}`} />}
        {f.solution_type && <Button size="sm" disabled={!ready} onClick={() => patch(f)} data-testid={`shortage-apply-${l.product_id}`}>Valider la solution</Button>}
        <select className={`${sel} ml-auto`} value={l.status} onChange={(e) => patch({ status: e.target.value })} aria-label="Statut" data-testid={`shortage-status-select-${l.product_id}`}>{Object.entries(SH_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      </div>}
    </div>
  );
}

function PartnerRequests({ ev, d, write, onDone }) {
  const open = d.lines.filter((l) => l.status !== "resolu");
  const [f, setF] = useState({ partners: "", deadline: "", note: "" });
  const send = () => {
    const partners = f.partners.split("\n").map((x) => x.split(";").map((y) => y.trim())).filter((x) => x[0]).map(([name, email]) => ({ name, email: email || "" }));
    if (!partners.length) { toast.error("Indiquez au moins un partenaire"); return; }
    api.post(`/events/${ev.id}/partner-requests`, { partners, shortage_ids: open.map((l) => l.id), deadline: f.deadline, note: f.note }).then(() => { toast.success("Demande(s) créée(s) : copiez le lien de réponse pour chaque partenaire"); setF({ partners: "", deadline: "", note: "" }); onDone(); }).catch(ko);
  };
  return (
    <div className="mt-4 border-t border-border pt-3 text-sm" data-testid="partner-requests">
      <div className="font-semibold">Demandes aux partenaires (sous-location)</div>
      {d.requests.map((r) => (<div key={r.id} className="mt-2 rounded-xl border border-border p-3" data-testid={`partner-request-${r.id}`}>
        <div className="flex flex-wrap items-center gap-2"><b>{r.partner_name}</b><span className="rounded-full bg-secondary px-2 py-0.5 text-xs" data-testid={`partner-request-status-${r.id}`}>{R_STATUS[r.status]}</span>
          <span className="text-xs text-muted-foreground">{r.items.map((i) => `${i.qty} × ${i.name}`).join(", ")}{r.deadline ? ` · réponse avant le ${fmtDate(r.deadline)}` : ""} · {r.email_sent ? "e-mail envoyé" : "aucun e-mail envoyé"}</span>
          <button className="ml-auto text-xs underline" onClick={() => navigator.clipboard.writeText(window.location.origin + r.link).then(() => toast.success("Lien de réponse copié"))} data-testid={`partner-request-link-${r.id}`}>Copier le lien de réponse</button></div>
        {r.reply && <div className="mt-1 text-xs" data-testid={`partner-reply-${r.id}`}>{r.reply.items.map((i) => `${i.available_qty} / ${i.requested} × ${i.name}${i.unit_cost != null ? ` à ${i.unit_cost} € HT` : ""}`).join(" · ")}{r.reply.cost_total != null ? ` — total ${r.reply.cost_total} € HT` : ""}{r.reply.conditions ? ` — ${r.reply.conditions}` : ""}{r.reply.comment ? ` — ${r.reply.comment}` : ""}
          {write && r.status === "repondue" && <Button size="sm" className="ml-2" onClick={() => api.post(`/partner-requests/${r.id}/accept`).then(() => { toast.success("Offre acceptée : manques couverts par le partenaire"); onDone(); }).catch(ko)} data-testid={`partner-accept-${r.id}`}>Accepter</Button>}</div>}
      </div>))}
      {write && open.length > 0 && <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-4">
        <Textarea rows={2} className="text-xs md:col-span-2" placeholder={"Un partenaire par ligne : Nom ; e-mail (optionnel)"} value={f.partners} onChange={(e) => setF({ ...f, partners: e.target.value })} data-testid="partner-request-partners" />
        <div><Input type="date" className="h-9 text-xs" title="Date limite de réponse" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} data-testid="partner-request-deadline" /><Input className="mt-1 h-9 text-xs" placeholder="Message" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></div>
        <Button size="sm" variant="outline" onClick={send} data-testid="partner-request-send">Demander aux partenaires ({open.length} manque{open.length > 1 ? "s" : ""})</Button>
      </div>}
    </div>
  );
}

export function EventShortages({ ev, write }) {
  const [d, setD] = useState(null);
  const [equipment, setEquipment] = useState([]);
  const version = JSON.stringify([(ev.equipment || []).map((l) => [l.equipment_id, l.qty]), ev.status, ev.start, ev.end, ev.venue_id, ev.kit_v]);
  const load = useCallback(() => api.get(`/events/${ev.id}/shortages`).then((r) => setD(r.data)).catch(() => {}), [ev.id]);
  useEffect(() => { load(); }, [load, version]);
  useEffect(() => { api.get("/equipment").then((r) => setEquipment(r.data.items || [])).catch(() => {}); }, []);
  if (!d || (!d.lines.length && !d.alerts.length && !d.requests.length)) return null;
  return (
    <Section title={`Manques (${d.open} à traiter)`} testid="shortages-section" actions={d.lines.length > 0 && <Button size="sm" variant="outline" onClick={() => downloadPdf(`/events/${ev.id}/shortages/pdf`, `manques-${ev.code}.pdf`).catch(() => toast.error("Impossible de générer le PDF"))} data-testid="shortages-pdf"><Download />PDF / impression</Button>}>
      <p className="mb-2 text-xs text-muted-foreground">Liste interne, jamais visible par le client. Elle se recalcule quand le stock, le matériel ou les dates changent ; les solutions choisies sont conservées.</p>
      <div className="space-y-2">{d.lines.map((l) => <Line key={l.id} l={l} write={write} solutions={d.solutions} equipment={equipment} onDone={load} />)}</div>
      {d.alerts.length > 0 && <div className="mt-3" data-testid="shortages-other"><div className="eyebrow">Manques humains et techniques</div>{d.alerts.map((a) => <p key={a} className="mt-1 rounded-lg bg-amber-500/10 p-2 text-sm text-amber-700"><AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{a}</p>)}</div>}
      {(d.lines.length > 0 || d.requests.length > 0) && <PartnerRequests ev={ev} d={d} write={write} onDone={load} />}
    </Section>
  );
}

export function ShortagesGlobal() {
  const [f, setF] = useState({ date_from: "", date_to: "" });
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/logistics/shortages", { params: f }).then((r) => setD(r.data)).catch(ko); }, [f]);
  if (!d) return <Loading />;
  return (
    <div data-testid="logistics-shortages">
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">Période du <Input type="date" className="w-44" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} data-testid="shortages-from" /> au <Input type="date" className="w-44" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} data-testid="shortages-to" /></div>
      {!d.lines.length ? <EmptyState title="Aucun manque à traiter sur cette période" /> : <>
        <div className="mb-4 flex flex-wrap gap-2" data-testid="shortages-events">{d.events.map((e) => <Link key={e.id} to={`/evenements/${e.id}?tab=materiel`} className="rounded-full border border-border px-3 py-1 text-xs font-semibold" data-testid={`shortages-event-${e.id}`}>{e.code} · {e.title} <span className="ml-1 rounded-full bg-red-600 px-1.5 text-white">{e.count}</span></Link>)}</div>
        <div className="card-soft overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="px-3 py-2">Produit</th><th className="px-3 py-2">Événement</th><th className="px-3 py-2">Dates</th><th className="px-3 py-2">Demandé</th><th className="px-3 py-2">Dispo</th><th className="px-3 py-2">Manquant</th><th className="px-3 py-2">Statut</th></tr></thead>
          <tbody>{d.lines.map((l) => <tr key={l.id} className="border-b border-border last:border-0" data-testid={`shortages-row-${l.id}`}><td className="px-3 py-2">{l.ref} {l.name}</td><td className="px-3 py-2"><Link className="underline" to={`/evenements/${l.event_id}?tab=materiel`}>{l.event_code}</Link> {l.event_title}</td><td className="px-3 py-2 text-xs">{dates(l)}</td><td className="px-3 py-2">{l.requested}</td><td className="px-3 py-2">{l.available}</td><td className="px-3 py-2 font-semibold text-red-600">{l.missing}</td><td className="px-3 py-2"><Badge s={l.status} id={l.id} />{l.solution ? <span className="ml-1 text-xs text-muted-foreground">{l.solution.label}</span> : null}</td></tr>)}</tbody></table></div></>}
    </div>
  );
}
