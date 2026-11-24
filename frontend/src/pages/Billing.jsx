import { useMemo } from "react";
import { QuoteEditor } from "@/components/billing/QuoteEditor";
import { QuoteList } from "@/components/billing/QuoteList";
import { useSearchParams } from "react-router-dom";
import { DirectQuoteDialog } from "@/components/billing/DirectQuoteDialog";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader, Loading, EmptyState, SearchPill, Field } from "@/components/common";
import { InvoiceCard, useBilling, useBillingPerms } from "@/components/billing/BillingParts";
import { api, errMsg } from "@/lib/api";
import { fmtEur2 } from "@/lib/constants";


function NewQuoteDialog({ open, onOpenChange, onSaved }) {
  const [events, setEvents] = useState([]);
  const [eid, setEid] = useState("");
  useEffect(() => { if (open) api.get("/events").then((r) => setEvents(r.data.filter((e) => e.status !== "cloture"))); }, [open]);
  const submit = async () => {
    try { const r = await api.post(`/events/${eid}/quotes`); toast.success(`Devis ${r.data.number} créé`); onSaved(r.data); onOpenChange(false); setEid(""); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle className="text-xl font-bold">Nouveau devis</DialogTitle></DialogHeader>
        <Field label="Événement (prestations et matériel repris automatiquement)">
          <Select value={eid || undefined} onValueChange={setEid}>
            <SelectTrigger data-testid="new-quote-event-select"><SelectValue placeholder="Choisir un événement" /></SelectTrigger>
            <SelectContent>{events.map((e) => <SelectItem key={e.id} value={e.id}>{e.code} · {e.title}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <DialogFooter><Button disabled={!eid} onClick={submit} data-testid="new-quote-submit">Créer le devis</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function Billing() {
  const { quotes, invoices, load } = useBilling();
  const { canQuote } = useBillingPerms();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState(null);
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") === "factures" ? "factures" : "devis";
  const setTab = (k) => setSp(k === "devis" ? {} : { tab: k });
  const keep = () => { const p = new URLSearchParams(sp); ["new", "client", "opp"].forEach((k) => p.delete(k)); setSp(p); };
  const direct = sp.get("new") === "1";
  const preset = useMemo(() => (sp.get("client") ? { client_id: sp.get("client") } : undefined), [sp]);
  if (!quotes || !invoices) return <Loading />;
  const match = (d) => !q || `${d.number} ${d.event_title} ${d.event_code} ${d.client?.name}`.toLowerCase().includes(q.toLowerCase());
  const due = invoices.reduce((n, i) => n + i.balance_due, 0);
  const rows = invoices.filter(match);
  return (
    <div>
      <PageHeader title="Devis & factures" subtitle={`${quotes.length} devis, ${invoices.length} facture(s) — ${fmtEur2(due)} à encaisser.`}
        actions={canQuote && <><Button variant="outline" onClick={() => setOpen(true)} data-testid="new-quote-button">Depuis un événement</Button><Button onClick={() => { const p = new URLSearchParams(sp); p.set("new", "1"); setSp(p); }} data-testid="new-direct-quote-button"><Plus />Nouveau devis</Button></>} />
      <div className="mb-6 flex flex-wrap items-center gap-3">
        {tab === "factures" && <SearchPill value={q} onChange={setQ} placeholder="Rechercher un numéro, client, événement…" testid="billing-search-input" />}
        <div className="ml-auto flex rounded-full border border-border p-1">
          {[["devis", `Devis (${quotes.length})`], ["factures", `Factures (${invoices.length})`]].map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)} data-testid={`billing-tab-${k}`} className={`rounded-full px-4 py-1.5 text-xs font-semibold transition-colors ${tab === k ? "bg-foreground text-background" : "text-muted-foreground"}`}>{l}</button>
          ))}
        </div>
      </div>
      {tab === "devis" ? <QuoteList quotes={quotes} invoices={invoices} reload={load} /> : !rows.length ? <EmptyState icon={FileText} title="Aucune facture" text="Transformez un devis en facture d'acompte ou de solde." /> : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="billing-list-factures">{rows.map((d) => <InvoiceCard key={d.id} i={d} onChanged={load} />)}</div>
      )}
      <NewQuoteDialog open={open} onOpenChange={setOpen} onSaved={(d) => { load(); setCreated(d); }} />
      {created && <QuoteEditor quote={created} onOpenChange={() => setCreated(null)} onSaved={load} />}
      <DirectQuoteDialog open={direct} onOpenChange={(o) => !o && keep()} onSaved={(d) => { if (sp.get("opp")) api.post(`/crm/opportunities/${sp.get("opp")}/quotes`, { quote_id: d.id }).catch(() => {}); load(); setCreated(d); }} preset={preset} />
    </div>
  );
}
