import { useEffect, useState } from "react";
import { EventFinance } from "@/components/finance/EventFinance";
import { Plus, Trash2, AlertTriangle, CheckCircle2, Circle, FolderOpen, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Section, Field, EmptyState } from "@/components/common";
import { api } from "@/lib/api";
import { fmtEur, fmtEur2, fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import EventBilling from "@/components/billing/EventBilling";
import EventDocuments from "@/components/events/EventDocuments";

const overlaps = (u, ev) => u.start <= ev.return_end.slice(0, 10) && u.end >= ev.setup_start.slice(0, 10);

export function EquipeTab({ ev, save }) {
  const { can } = useMe();
  const write = can("events:write");
  const [team, setTeam] = useState([]);
  const [lines, setLines] = useState([]);
  useEffect(() => { api.get("/team").then((r) => setTeam(r.data)); }, []);
  useEffect(() => { setLines((ev.team || []).map((t) => ({ ...t }))); }, [ev]);
  const upd = (i, k, v) => setLines(lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const clean = (l) => ({ member_id: l.member_id, role: l.role || "", start: l.start || ev.setup_start, end: l.end || ev.return_end, confirmed: !!l.confirmed });
  const dirty = JSON.stringify(lines.map(clean)) !== JSON.stringify((ev.team || []).map(clean));
  return (
    <Section title="Équipe affectée" testid="equipe-section"
      actions={write && <Button variant="outline" data-testid="add-team-line-button" onClick={() => setLines([...lines, { member_id: "", role: "", confirmed: false }])}><Plus className="mr-1 h-4 w-4" />Affecter</Button>}>
      {!lines.length ? <EmptyState title="Aucun technicien affecté" text="Affectez l'équipe nécessaire à cet événement." /> : (
        <div className="space-y-2.5">
          {lines.map((l, i) => {
            const m = team.find((t) => t.id === l.member_id);
            const busy = m?.unavailabilities?.find((u) => overlaps(u, ev));
            return (
              <div key={i} className="flex flex-wrap items-center gap-3 rounded-xl border border-border p-3" data-testid={`team-line-${i}`}>
                <span className="h-8 w-8 shrink-0 rounded-full" style={{ background: m?.color || "#ddd" }} />
                <Select disabled={!write} value={l.member_id || undefined} onValueChange={(v) => upd(i, "member_id", v)}>
                  <SelectTrigger className="w-52" data-testid={`team-member-select-${i}`}><SelectValue placeholder="Choisir un membre" /></SelectTrigger>
                  <SelectContent>{team.filter((t) => t.active).map((t) => <SelectItem key={t.id} value={t.id}>{t.name} · {t.job}</SelectItem>)}</SelectContent>
                </Select>
                <Input disabled={!write} className="w-48" placeholder="Rôle (ex. Ingénieur son)" value={l.role} onChange={(e) => upd(i, "role", e.target.value)} data-testid={`team-role-input-${i}`} />
                <label className="flex items-center gap-2 text-xs"><Switch disabled={!write} checked={!!l.confirmed} onCheckedChange={(v) => upd(i, "confirmed", v)} />Présence confirmée</label>
                {busy && <span className="flex items-center gap-1 text-xs font-medium text-amber-700"><AlertTriangle className="h-3.5 w-3.5" />Indisponible ({busy.reason || "absence"})</span>}
                {write && <Button size="icon" variant="ghost" className="ml-auto" onClick={() => setLines(lines.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>}
              </div>
            );
          })}
        </div>
      )}
      {write && dirty && <div className="mt-4 flex justify-end"><Button disabled={lines.some((l) => !l.member_id)} onClick={() => save({ team: lines.map(clean) }, "Équipe enregistrée")} data-testid="save-team-button">Enregistrer l'équipe</Button></div>}
    </Section>
  );
}

export function PlanningTab({ ev, save }) {
  const { can } = useMe();
  const write = can("events:write");
  const [lines, setLines] = useState([]);
  useEffect(() => { setLines((ev.planning || []).map((p) => ({ ...p }))); }, [ev]);
  const upd = (i, k, v) => setLines(lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const sorted = [...(ev.planning || [])].sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Section title="Chronogramme" testid="planning-timeline">
        {!sorted.length ? <div className="text-sm text-muted-foreground">Aucune étape.</div> : (
          <ol className="relative ml-2 border-l border-border">
            {sorted.map((p, i) => (
              <li key={i} className="mb-5 ml-5">
                <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-primary" />
                <div className="text-xs text-muted-foreground">{fmtDate(p.date, { weekday: "short", day: "numeric", month: "short" })} · {p.time}</div>
                <div className="text-sm font-medium">{p.label}</div>
              </li>
            ))}
          </ol>
        )}
      </Section>
      {write && (
        <Section title="Modifier les étapes" actions={<Button variant="outline" size="sm" data-testid="add-planning-line" onClick={() => setLines([...lines, { date: ev.start.slice(0, 10), time: "18:00", label: "" }])}><Plus className="mr-1 h-4 w-4" />Étape</Button>}>
          <div className="space-y-2">
            {lines.map((l, i) => (
              <div key={i} className="flex gap-2">
                <Input type="date" className="w-40" value={l.date} onChange={(e) => upd(i, "date", e.target.value)} />
                <Input type="time" className="w-28" value={l.time} onChange={(e) => upd(i, "time", e.target.value)} />
                <Input placeholder="Balance son, accueil public…" value={l.label} onChange={(e) => upd(i, "label", e.target.value)} data-testid={`planning-label-${i}`} />
                <Button size="icon" variant="ghost" onClick={() => setLines(lines.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>
              </div>
            ))}
          </div>
          <div className="mt-4 flex justify-end"><Button disabled={lines.some((l) => !l.label || !l.time)} onClick={() => save({ planning: lines }, "Planning enregistré")} data-testid="save-planning-button">Enregistrer</Button></div>
        </Section>
      )}
    </div>
  );
}

export function DocumentsTab({ ev }) {
  return <EventDocuments ev={ev} />;
}

const Row = ({ label, value, strong, testid }) => (
  <div className={`flex justify-between py-2 ${strong ? "border-t border-border pt-3 font-semibold" : "text-sm"}`}><span className={strong ? "" : "text-muted-foreground"}>{label}</span><span data-testid={testid}>{value}</span></div>
);

export function FinancesTab(props) {
  return <><EventFinance eid={props.ev.id} /><FinanceSummary {...props} /><EventBilling ev={props.ev} reload={props.reload} /></>;
}

function FinanceSummary({ ev, save, setStatus }) {
  const { can } = useMe();
  const write = can("finance:write");
  const manual = write && !ev.invoices_count;
  const [f, setF] = useState({});
  useEffect(() => { setF({ deposit_paid: ev.deposit_paid || 0, extra_costs: ev.extra_costs || 0 }); }, [ev]);
  const margin = ev.amount_ht - ev.costs_total;
  const Check = ({ ok, label }) => <div className="flex items-center gap-2 text-sm">{ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Circle className="h-4 w-4 text-muted-foreground" />}{label}</div>;
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <Section title="Chiffrage" testid="finance-summary">
        <Row label="Matériel" value={fmtEur2(ev.amount_equipment)} />
        <Row label="Prestations" value={fmtEur2(ev.amount_services)} />
        <Row label="Total HT" value={fmtEur2(ev.amount_ht)} strong testid="finance-total-ht" />
        <Row label="TVA 20 %" value={fmtEur2(ev.amount_ttc - ev.amount_ht)} />
        <Row label="Total TTC" value={fmtEur2(ev.amount_ttc)} strong testid="finance-total-ttc" />
        {ev.budget > 0 && <Row label="Budget client" value={fmtEur(ev.budget)} />}
      </Section>
      <Section title="Rentabilité prévisionnelle" testid="finance-margin">
        <Row label="CA HT" value={fmtEur2(ev.amount_ht)} />
        <Row label="Coûts (prestataires + frais)" value={`− ${fmtEur2(ev.costs_total)}`} />
        <Row label="Marge" value={`${fmtEur2(margin)} (${ev.amount_ht ? Math.round((margin / ev.amount_ht) * 100) : 0} %)`} strong testid="finance-margin-value" />
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Field label="Acompte encaissé (€)"><Input type="number" min="0" disabled={!manual} value={f.deposit_paid} onChange={(e) => setF({ ...f, deposit_paid: e.target.value })} data-testid="deposit-paid-input" /></Field>
          <Field label="Frais annexes (€)"><Input type="number" min="0" disabled={!write} value={f.extra_costs} onChange={(e) => setF({ ...f, extra_costs: e.target.value })} data-testid="extra-costs-input" /></Field>
        </div>
        {write && <Button variant="outline" className="mt-3 w-full" onClick={() => save({ ...(manual ? { deposit_paid: Number(f.deposit_paid) || 0 } : {}), extra_costs: Number(f.extra_costs) || 0 }, "Finances enregistrées")} data-testid="save-finance-button">Enregistrer</Button>}
        <div className="mt-3 text-xs text-muted-foreground">Reste à encaisser : <b>{fmtEur2(ev.invoice_paid ? 0 : Math.max(0, ev.amount_ttc - (ev.deposit_paid || 0)))}</b></div>
      </Section>
      <Section title="Clôture du dossier" testid="closing-section">
        <div className="space-y-3">
          <Check ok={ev.material_returned} label="Matériel retourné au dépôt" />
          <div className="flex items-center justify-between"><Check ok={ev.invoice_paid} label="Facture soldée" />
            {manual && <Switch checked={!!ev.invoice_paid} onCheckedChange={(v) => save({ invoice_paid: v }, v ? "Facture marquée soldée" : "Facture marquée non soldée")} data-testid="invoice-paid-switch" />}</div>
        </div>
        <Button className="mt-5 w-full" disabled={!ev.can_close || ev.status === "cloture" || !(write || can("events:write"))} onClick={() => setStatus("cloture")} data-testid="close-event-button">
          <Lock className="mr-1.5 h-4 w-4" />{ev.status === "cloture" ? "Dossier clôturé" : "Clôturer l'événement"}
        </Button>
        {!ev.can_close && <p className="mt-2 text-xs text-muted-foreground">La clôture exige le retour du matériel et une facture soldée.</p>}
      </Section>
    </div>
  );
}

export function HistoryTab({ ev }) {
  return (
    <Section title="Historique des modifications" testid="history-section">
      <div className="divide-y divide-border">
        {(ev.history || []).map((h, i) => (
          <div key={i} className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:gap-4">
            <div className="w-44 shrink-0 text-xs text-muted-foreground">{new Date(h.at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</div>
            <div className="text-sm"><span className="font-medium">{h.action}</span> — {h.detail}</div>
            <div className="text-xs text-muted-foreground sm:ml-auto">{h.by}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}
