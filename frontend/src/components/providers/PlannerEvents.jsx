import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Info, Loading } from "@/components/common";
import { api, downloadPdf, errMsg } from "@/lib/api";
import { fmtDate, fmtEur2, statusLabel } from "@/lib/constants";

const th = "px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground";
const td = "px-3 py-2.5 align-top";
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-sm";
const BASES = [["ca_ht", "Devis signés (à défaut total de l'événement)"], ["invoiced_ht", "Facturé"], ["event_ht", "Total des événements"]];

export function PlannerEvents({ providerId }) {
  const [year, setYear] = useState("");
  const [d, setD] = useState(null);
  useEffect(() => { api.get(`/providers/${providerId}/events`, { params: { year: year || undefined } }).then((r) => setD(r.data)).catch((e) => toast.error(errMsg(e))); }, [providerId, year]);
  if (!d) return <Loading />;
  const i = d.indicators;
  return (
    <div data-testid="planner-events">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select className={sel} value={year} onChange={(e) => setYear(e.target.value)} data-testid="planner-events-year"><option value="">Toutes les années</option>{d.years.map((y) => <option key={y} value={y}>{y}</option>)}</select>
        <Button size="sm" variant="outline" className="ml-auto" onClick={() => downloadPdf(`/providers/${providerId}/events/export${year ? `?year=${year}` : ""}`, "evenements-apportes.csv").catch((e) => toast.error(errMsg(e)))} data-testid="planner-events-export"><Download />Exporter en CSV</Button>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4" data-testid="planner-indicators">
        <Info label="Événements" value={`${i.count} (${i.upcoming} à venir, ${i.past} passés)`} />
        <Info label="CA HT généré" value={fmtEur2(i.ca_ht)} /><Info label="HT facturé" value={fmtEur2(i.invoiced_ht)} /><Info label="Panier moyen HT" value={fmtEur2(i.average_basket)} />
        <Info label="Commissions à verser" value={fmtEur2(i.commission_due)} /><Info label="Commissions versées" value={fmtEur2(i.commission_paid)} />
        <Info label="Délai moyen demande → événement" value={i.lead_days == null ? "" : `${i.lead_days} jours`} />
        <Info label="Lieux les plus fréquents" value={i.top_venues.map(([v, n]) => `${v} (${n})`).join(", ")} />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">CA HT généré : montant HT des devis signés, et à défaut le total HT de l'événement.</p>
      {d.by_year.length > 0 && <div className="mt-4 overflow-x-auto"><table className="w-full text-sm" data-testid="planner-by-year"><thead><tr className="border-b border-border"><th className={th}>Année</th><th className={th}>Événements</th>{BASES.map(([k, l]) => <th key={k} className={th}>{l} (HT)</th>)}</tr></thead>
        <tbody>{d.by_year.map((y) => <tr key={y.year} className="border-b border-border last:border-b-0"><td className={td}>{y.year}</td><td className={td}>{y.count}</td>{BASES.map(([k]) => <td key={k} className={td}>{fmtEur2(y[k])}</td>)}</tr>)}</tbody></table></div>}
      {!d.rows.length ? <p className="py-8 text-center text-sm text-muted-foreground" data-testid="planner-events-empty">Aucun événement apporté.</p> : (
        <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[820px] text-sm" data-testid="planner-events-table">
          <thead><tr className="border-b border-border"><th className={th}>Date</th><th className={th}>Interlocuteur</th><th className={th}>Client</th><th className={th}>Lieu</th><th className={th}>Catégorie</th><th className={th}>Statut</th><th className={th}>HT devis / facturé</th><th className={th}>Commission</th></tr></thead>
          <tbody>{d.rows.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-b-0" data-testid={`planner-event-${r.id}`}>
              <td className={td}><Link to={`/evenements/${r.id}`} className="font-medium hover:underline">{fmtDate(r.date)}</Link><div className="text-xs text-muted-foreground">{r.title}</div></td>
              <td className={td} data-testid={`planner-event-person-${r.id}`}>{r.interlocutor || "—"}</td><td className={td}>{r.client || "—"}</td><td className={td}>{r.venue || "—"}</td><td className={td}>{r.type}</td><td className={td}>{statusLabel(r.status)}</td>
              <td className={td}>{r.signed_ht == null ? <>{fmtEur2(r.event_ht)} <span className="text-xs text-muted-foreground">(pas de devis signé)</span></> : fmtEur2(r.signed_ht)} / {fmtEur2(r.invoiced_ht)}</td>
              <td className={td}>{r.commission ? `${fmtEur2(r.commission)} — ${r.commission_status === "paid" ? "versée" : "à verser"}` : "—"}</td>
            </tr>))}</tbody></table></div>)}
    </div>
  );
}

export function PlannerRanking({ onOpen, categories = [] }) {
  const [type, setType] = useState("");
  const [d, setD] = useState(null);
  const [by, setBy] = useState("ca_ht");
  useEffect(() => { api.get("/organizers/ranking", { params: { type: type || undefined } }).then((r) => setD(r.data)).catch((e) => toast.error(errMsg(e))); }, [type]);
  if (!d) return <Loading />;
  const rows = [...d.rows].sort((a, b) => b[by] - a[by]);
  return (
    <div className="card-soft p-5" data-testid="planner-ranking">
      <div className="mb-4 flex flex-wrap items-center gap-3"><h2 className="text-lg font-semibold">Organisateurs — {d.year}</h2>
        <select className={sel} value={type} onChange={(e) => setType(e.target.value)} data-testid="planner-ranking-type"><option value="">Tous les types</option>{categories.filter((c) => c.is_organizer).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select>
        <select className={`${sel} ml-auto`} value={by} onChange={(e) => setBy(e.target.value)} data-testid="planner-ranking-sort"><option value="ca_ht">Classer par CA HT apporté</option><option value="count">Classer par nombre d'événements</option></select></div>
      {!rows.length ? <p className="py-8 text-center text-sm text-muted-foreground" data-testid="planner-ranking-empty">Aucun événement apporté par un organisateur cette année.</p> : (
        <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="border-b border-border"><th className={th}>#</th><th className={th}>Organisateur</th><th className={th}>Événements</th>{BASES.map(([k, l]) => <th key={k} className={th}>{l} (HT)</th>)}<th className={th}>Commissions à verser</th></tr></thead>
          <tbody>{rows.map((r, n) => (
            <tr key={r.contact_id} className="cursor-pointer border-b border-border last:border-b-0 hover:bg-secondary/50" onClick={() => onOpen(r.provider_id)} data-testid={`planner-ranking-row-${r.provider_id}`}>
              <td className={td}>{n + 1}</td><td className={td}><b>{r.display_name}</b><div className="text-xs text-muted-foreground">{[r.type_label, r.company, r.city].filter(Boolean).join(" · ")}</div></td><td className={td}>{r.count}</td>
              {BASES.map(([k]) => <td key={k} className={td}>{fmtEur2(r[k])}</td>)}<td className={td}>{fmtEur2(r.commission_due)}</td>
            </tr>))}</tbody></table></div>)}
    </div>
  );
}
