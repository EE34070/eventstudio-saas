import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { BellRing, Copy, Send, User, Calendar, Banknote, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { PageHeader, Loading, EmptyState, Meta } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { fmtEur2, fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

export default function Relances() {
  const { can } = useMe();
  const write = can("finance:write");
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState("");
  const load = useCallback(() => api.get("/reminders").then((r) => setD(r.data)).catch((err) => toast.error(errMsg(err))), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return <Loading />;
  const send = async (r) => {
    setBusy(r.id);
    try { await api.post(`/invoices/${r.id}/remind`); toast.success(`Relance envoyée à ${r.client_email}`); load(); } catch (err) { toast.error(errMsg(err)); }
    setBusy("");
  };
  const toggle = async (auto) => { try { await api.put("/reminders/settings", { auto }); toast.success(auto ? "Relances automatiques activées" : "Relances automatiques désactivées"); load(); } catch (err) { toast.error(errMsg(err)); } };
  const copy = (r) => navigator.clipboard.writeText(`${r.subject}\n\n${r.message}`).then(() => toast.success("Message copié"), () => toast.error("Copie impossible"));
  return (
    <div>
      <PageHeader title="Relances impayés" subtitle={`${d.rows.length} facture(s) en retard — ${fmtEur2(d.total_due)} à encaisser.`} />
      <div className="card-soft mb-6 flex flex-wrap items-center gap-4 p-5" data-testid="auto-reminders-card">
        <BellRing className="h-5 w-5" />
        <div className="min-w-0 flex-1"><div className="font-semibold">Relances automatiques</div><div className="text-sm text-muted-foreground">Un e-mail part chaque matin à 9 h pour les factures en retard de {d.steps.join(", ")} jours.</div></div>
        <Switch checked={d.auto} disabled={!write} onCheckedChange={toggle} data-testid="auto-reminders-switch" />
      </div>
      {!d.rows.length ? <EmptyState icon={BellRing} title="Aucune facture en retard" text="Les factures dont l'échéance est dépassée apparaissent ici avec une relance prête à envoyer." /> : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="reminders-list">
          {d.rows.map((r) => (
            <div key={r.id} className="card-soft p-6" data-testid={`reminder-card-${r.number}`}>
              <div className="flex gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><span className="text-lg font-semibold">{r.number}</span><span className="rounded-full bg-red-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-red-600 dark:text-red-400" data-testid={`reminder-late-${r.number}`}>{r.days_late} j de retard</span></div>
                  <Link to={`/evenements/${r.event_id}`} className="block truncate text-sm text-muted-foreground hover:text-foreground">{r.event_title}</Link>
                </div>
                <div className="text-right"><div className="text-lg font-bold">{fmtEur2(r.balance_due)}</div><div className="text-xs text-muted-foreground">reste dû</div></div>
              </div>
              <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1">
                <Meta icon={User}>{r.client_name || "—"}</Meta>
                <Meta icon={Mail}>{r.client_email || "Pas d'e-mail"}</Meta>
                <Meta icon={Calendar}>Échéance {fmtDate(r.due_date)}</Meta>
                <Meta icon={Banknote} testid={`reminder-count-${r.number}`}>{r.reminders.length} relance(s) envoyée(s)</Meta>
              </div>
              <div className="mt-4 rounded-2xl border border-border p-4 text-sm" data-testid={`reminder-message-${r.number}`}>
                <div className="font-semibold">{r.subject}</div>
                <p className="mt-2 whitespace-pre-line break-words text-muted-foreground">{r.message}</p>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button size="sm" onClick={() => copy(r)} data-testid={`reminder-copy-${r.number}`}><Copy />Copier</Button>
                {write && <Button size="sm" className="ml-auto" disabled={busy === r.id || !r.client_email} onClick={() => send(r)} data-testid={`reminder-send-${r.number}`}><Send />{busy === r.id ? "Envoi…" : `Envoyer la relance n° ${r.next_level}`}</Button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
