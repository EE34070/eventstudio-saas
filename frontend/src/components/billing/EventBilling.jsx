import { toast } from "sonner";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Section } from "@/components/common";
import { QuoteCard, InvoiceCard, useBilling, useBillingPerms } from "@/components/billing/BillingParts";
import { api, errMsg } from "@/lib/api";

export default function EventBilling({ ev, reload }) {
  const { quotes, invoices, load } = useBilling(ev.id);
  const { canQuote } = useBillingPerms();
  const changed = () => { load(); reload(); };
  const create = async () => {
    try { const r = await api.post(`/events/${ev.id}/quotes`); toast.success(`Devis ${r.data.number} créé`); changed(); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Section title="Devis & factures" className="mt-6" testid="event-billing"
      actions={canQuote && <Button size="sm" onClick={create} data-testid="event-create-quote-button"><Plus />Créer un devis</Button>}>
      {quotes && invoices && !quotes.length && <div className="text-sm text-muted-foreground">Aucun devis pour cet événement. Le devis reprend les prestations et le matériel saisis.</div>}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {invoices && (quotes || []).map((q) => <QuoteCard key={q.id} q={q} invoices={invoices} onChanged={changed} showEvent={false} />)}
        {(invoices || []).map((i) => <InvoiceCard key={i.id} i={i} onChanged={changed} showEvent={false} />)}
      </div>
    </Section>
  );
}
