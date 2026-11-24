import { useCallback, useEffect, useState } from "react";
import { TrashBtn, Pick, BulkDelete } from "@/components/Trash";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { FileText, Receipt, Download, Pencil, Link2, Send, PenLine, RefreshCw, XCircle, Plus, Trash2, Calendar, User, Banknote, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Field, Meta } from "@/components/common";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { fmtEur2, fmtDate, dayKey } from "@/lib/constants";
import { useMe } from "@/context/MeContext";
import { QuoteStock } from "@/components/stock/Availability";
import { QuoteEditor } from "@/components/billing/QuoteEditor";
import { DuplicateButton } from "@/components/billing/DuplicateQuote";
import { QuoteDocsButtons } from "@/components/billing/QuoteDocs";

export const Q_STATUS = { brouillon: "Brouillon", envoye: "Envoyé", vu: "Vu", negociation: "En négociation", accepte: "Accepté", refuse: "Refusé", expire: "Expiré", remplace: "Remplacé" };
const Q_OPEN = ["brouillon", "envoye", "vu", "negociation"];
export const I_STATUS = { emise: "À encaisser", partielle: "Partiellement payée", payee: "Payée", annulee: "Annulée" };
const METHODS = { virement: "Virement", cb: "Carte bancaire", cheque: "Chèque", especes: "Espèces" };
const VATS = [20, 10, 5.5, 0];
const blue = "bg-blue-500/10 text-blue-600 dark:text-blue-400";
const green = "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
const TONE = { brouillon: "bg-secondary text-muted-foreground", envoye: blue, vu: blue, negociation: "bg-amber-500/10 text-amber-600 dark:text-amber-400", expire: "bg-secondary text-muted-foreground", remplace: "bg-secondary text-muted-foreground", accepte: green, refuse: "bg-red-500/10 text-red-600 dark:text-red-400",
  emise: "bg-amber-500/10 text-amber-600 dark:text-amber-400", partielle: blue, payee: green };

export const DocBadge = ({ status, label, testid }) => (
  <span data-testid={testid} className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${TONE[status]}`}>{label}</span>
);

export function useBillingPerms() {
  const { can } = useMe();
  return { canQuote: can("finance:write") || can("events:write"), canInvoice: can("finance:write") };
}

export function useBilling(eventId) {
  const [quotes, setQuotes] = useState(null);
  const [invoices, setInvoices] = useState(null);
  const load = useCallback(() => {
    const params = eventId ? { event_id: eventId } : {};
    api.get("/quotes", { params }).then((r) => setQuotes(r.data));
    api.get("/invoices", { params }).then((r) => setInvoices(r.data));
  }, [eventId]);
  useEffect(() => { load(); }, [load]);
  return { quotes, invoices, load };
}

const sum = (lines) => {
  const ht = lines.reduce((n, l) => n + (Number(l.qty) || 0) * (Number(l.unit_price) || 0), 0);
  const vat = lines.reduce((n, l) => n + ((Number(l.qty) || 0) * (Number(l.unit_price) || 0) * (Number(l.vat) || 0)) / 100, 0);
  return { ht, vat, ttc: ht + vat };
};

export function QuoteDialog({ quote, onOpenChange, onSaved }) {
  const [f, setF] = useState(null);
  useEffect(() => { if (quote) setF({ lines: quote.lines.map((l) => ({ ...l })), deposit_percent: quote.deposit_percent, valid_until: quote.valid_until, notes: quote.notes || "" }); }, [quote]);
  if (!quote || !f) return null;
  const upd = (i, k, v) => setF({ ...f, lines: f.lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)) });
  const t = sum(f.lines);
  const submit = async (e) => {
    e.preventDefault();
    const body = { ...f, deposit_percent: Number(f.deposit_percent) || 0, lines: f.lines.map((l) => ({ label: l.label, description: l.description || "", qty: Number(l.qty), unit_price: Number(l.unit_price) || 0, vat: Number(l.vat), equipment_id: l.equipment_id || "" })) };
    try { await api.put(`/quotes/${quote.id}`, body); toast.success("Devis enregistré"); onSaved(); onOpenChange(false); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
        <DialogHeader><DialogTitle className="text-xl font-bold">Devis {quote.number}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="space-y-4" data-testid="quote-form">
          <div className="space-y-2">
            {f.lines.map((l, i) => (
              <div key={i} className="grid grid-cols-12 gap-2 rounded-2xl border border-border p-3" data-testid={`quote-line-${i}`}>
                <Input required className="col-span-12 sm:col-span-5" placeholder="Désignation" value={l.label} onChange={(e) => upd(i, "label", e.target.value)} data-testid={`quote-line-label-${i}`} />
                <Input required type="number" min="0.01" step="any" className="col-span-3 sm:col-span-2" title="Quantité" value={l.qty} onChange={(e) => upd(i, "qty", e.target.value)} data-testid={`quote-line-qty-${i}`} />
                <Input required type="number" step="any" className="col-span-4 sm:col-span-2" title="Prix unitaire HT" value={l.unit_price} onChange={(e) => upd(i, "unit_price", e.target.value)} data-testid={`quote-line-price-${i}`} />
                <select className="col-span-3 rounded-md border border-input bg-transparent px-2 text-sm sm:col-span-2" title="TVA" value={l.vat} onChange={(e) => upd(i, "vat", e.target.value)} data-testid={`quote-line-vat-${i}`}>
                  {[...new Set([...VATS, Number(l.vat)])].map((v) => <option key={v} value={v}>{String(v).replace(".", ",")} %</option>)}
                </select>
                <Button type="button" size="icon" variant="ghost" className="col-span-2 sm:col-span-1" disabled={f.lines.length === 1} onClick={() => setF({ ...f, lines: f.lines.filter((_, j) => j !== i) })} data-testid={`quote-line-remove-${i}`}><Trash2 /></Button>
              </div>
            ))}
            <Button type="button" size="sm" onClick={() => setF({ ...f, lines: [...f.lines, { label: "", description: "", qty: 1, unit_price: 0, vat: 20 }] })} data-testid="quote-add-line"><Plus />Ligne</Button>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Acompte à la commande (%)"><Input type="number" min="0" max="99" step="any" value={f.deposit_percent} onChange={(e) => setF({ ...f, deposit_percent: e.target.value })} data-testid="quote-deposit-input" /></Field>
            <Field label="Valable jusqu'au"><Input type="date" value={f.valid_until} onChange={(e) => setF({ ...f, valid_until: e.target.value })} data-testid="quote-valid-input" /></Field>
            <Field label="Notes (visibles sur le PDF)" className="col-span-2"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
          </div>
          <div className="ml-auto w-full max-w-xs text-sm" data-testid="quote-totals">
            <div className="flex justify-between py-1 text-muted-foreground"><span>Total HT</span><span>{fmtEur2(t.ht)}</span></div>
            <div className="flex justify-between py-1 text-muted-foreground"><span>TVA</span><span>{fmtEur2(t.vat)}</span></div>
            <div className="flex justify-between border-t border-border py-2 font-bold"><span>Total TTC</span><span data-testid="quote-total-ttc">{fmtEur2(t.ttc)}</span></div>
          </div>
          <DialogFooter><Button data-testid="quote-form-submit">Enregistrer</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function PaymentDialog({ invoice, onOpenChange, onSaved, write }) {
  const [inv, setInv] = useState(invoice);
  const [f, setF] = useState({ amount: "", date: dayKey(new Date()), method: "virement", reference: "" });
  useEffect(() => { setInv(invoice); if (invoice) setF((x) => ({ ...x, amount: invoice.balance_due || "" })); }, [invoice]);
  if (!inv) return null;
  const done = (r, msg) => { setInv(r.data); setF((x) => ({ ...x, amount: r.data.balance_due || "", reference: "" })); toast.success(msg); onSaved(); };
  const submit = async (e) => {
    e.preventDefault();
    try { done(await api.post(`/invoices/${inv.id}/payments`, { ...f, amount: Number(f.amount) }), "Paiement enregistré"); } catch (err) { toast.error(errMsg(err)); }
  };
  const remove = async (pid) => { try { done(await api.delete(`/invoices/${inv.id}/payments/${pid}`), "Paiement annulé"); } catch (err) { toast.error(errMsg(err)); } };
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle className="text-xl font-bold">Paiements · {inv.number}</DialogTitle></DialogHeader>
        <div className="grid grid-cols-3 gap-3 text-sm">
          <div><div className="eyebrow">Total TTC</div><div className="font-semibold">{fmtEur2(inv.total_ttc)}</div></div>
          <div><div className="eyebrow">Encaissé</div><div className="font-semibold" data-testid="payment-paid-amount">{fmtEur2(inv.paid_amount)}</div></div>
          <div><div className="eyebrow">Reste à payer</div><div className="font-semibold" data-testid="payment-balance">{fmtEur2(inv.balance_due)}</div></div>
        </div>
        <div className="divide-y divide-border" data-testid="payments-list">
          {!inv.payments.length && <div className="py-2 text-sm text-muted-foreground">Aucun paiement enregistré.</div>}
          {inv.payments.map((p) => (
            <div key={p.id} className="flex items-center gap-3 py-2 text-sm" data-testid={`payment-row-${p.id}`}>
              <div className="flex-1"><b>{fmtEur2(p.amount)}</b> · {METHODS[p.method] || p.method} · {fmtDate(p.date)}{p.reference ? ` · ${p.reference}` : ""}</div>
              {write && <Button size="icon" variant="ghost" onClick={() => remove(p.id)} title="Annuler ce paiement" data-testid={`payment-remove-${p.id}`}><Trash2 /></Button>}
            </div>
          ))}
        </div>
        {write && inv.balance_due > 0 && (
          <form onSubmit={submit} className="grid grid-cols-2 gap-3" data-testid="payment-form">
            <Field label="Montant (€)"><Input required type="number" min="0.01" step="0.01" max={inv.balance_due} value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} data-testid="payment-amount-input" /></Field>
            <Field label="Date"><Input required type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} data-testid="payment-date-input" /></Field>
            <Field label="Moyen"><Select value={f.method} onValueChange={(v) => setF({ ...f, method: v })}><SelectTrigger data-testid="payment-method-select"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(METHODS).map(([k, l]) => <SelectItem key={k} value={k}>{l}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="Référence"><Input value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} data-testid="payment-reference-input" /></Field>
            <DialogFooter className="col-span-2"><Button data-testid="payment-form-submit"><Plus />Enregistrer le paiement</Button></DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

const pdf = (path, name) => downloadPdf(path, `${name}.pdf`).catch(() => toast.error("Impossible de générer le PDF"));

export function QuoteCard({ q, invoices, onChanged, showEvent = true }) {
  const { canQuote, canInvoice } = useBillingPerms();
  const [edit, setEdit] = useState(false);
  const invs = invoices.filter((i) => i.quote_id === q.id);
  const kinds = invs.map((i) => i.kind);
  const sig = q.signature?.status;
  const SIG = { ongoing: ["envoye", "Signature en attente"], done: ["accepte", "Signé"], declined: ["refuse", "Signature refusée"], expired: ["brouillon", "Signature expirée"], canceled: ["brouillon", "Signature annulée"] };
  const live = q.active !== false;
  const free = live && !invs.length && !["ongoing", "done"].includes(sig);
  const act = async (fn, msg) => { try { await fn(); toast.success(msg); onChanged(); } catch (err) { toast.error(errMsg(err)); } };
  const bill = (kind) => act(() => api.post(`/quotes/${q.id}/invoice`, { kind }), kind === "acompte" ? "Facture d'acompte émise" : "Facture de solde émise");
  return (
    <div className="card-soft hover-lift p-6" data-testid={`quote-card-${q.number}`}>
      <div className="flex gap-4">
        <div className="flex shrink-0 flex-col items-center gap-3"><FileText className="mt-0.5 h-5 w-5" /><TrashBtn kind="quote" id={q.id} name={q.number} onDone={onChanged} /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><span className="text-lg font-semibold">{q.number}</span>{(q.version || 1) > 1 && <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-semibold" data-testid={`quote-version-badge-${q.id}`}>V{q.version}</span>}<DocBadge status={q.status} label={Q_STATUS[q.status]} testid={`quote-status-${q.number}`} />{q.signature?.provider === "otp" && sig === "done" && <span className="text-xs text-muted-foreground">signature simple (OTP)</span>}{sig && <DocBadge status={SIG[sig][0]} label={SIG[sig][1]} testid={`quote-signature-${q.number}`} />}</div>
          {showEvent && <Link to={`/evenements/${q.event_id}`} className="block truncate text-sm text-muted-foreground hover:text-foreground">{q.event_code} · {q.event_title}</Link>}
        </div>
        <div className="text-right"><div className="text-lg font-bold" data-testid={`quote-ttc-${q.number}`}>{fmtEur2(q.total_ttc)}</div><div className="text-xs text-muted-foreground">TTC</div></div>
      </div>
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 sm:pl-9">
        <Meta icon={User}>{q.client?.name || "Client à définir"}</Meta>
        <Meta icon={Calendar}>{fmtDate(q.date)}</Meta>
        <Meta icon={Clock}>Valable jusqu'au {fmtDate(q.valid_until)}</Meta>
        <Meta icon={Banknote}>Acompte {String(q.deposit_percent).replace(".", ",")} %</Meta>
        {q.sent_to && <Meta icon={Send} testid={`quote-sent-${q.number}`}>Envoyé à {q.sent_to}</Meta>}
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-2 sm:pl-9">
        <Button size="sm" onClick={() => pdf(`/quotes/${q.id}/pdf`, q.number)} data-testid={`quote-pdf-${q.number}`}><Download />PDF</Button>
        <Button size="sm" onClick={async () => { try { const r = await api.post(`/quotes/${q.id}/share`); const url = `${window.location.origin}/devis/${r.data.token}`; navigator.clipboard?.writeText(url).catch(() => {}); toast.success("Lien du devis copié"); window.open(`${url}?apercu=1`, "_blank", "noopener"); } catch (err) { toast.error(errMsg(err)); } }} data-testid={`quote-link-${q.number}`}><Link2 />Devis en ligne</Button>
        {canQuote && live && q.status !== "refuse" && <Button size="sm" onClick={() => act(() => api.post(`/quotes/${q.id}/send`).catch((e) => { const d = e.response?.data?.detail; if (d?.code === "margin_pending" && window.confirm(`${d.message} Envoyer quand même ?`)) return api.post(`/quotes/${q.id}/send?force=true`); throw e; }), "Devis envoyé au client")} data-testid={`quote-send-${q.number}`}><Send />Envoyer par e-mail</Button>}
        {canQuote && live && q.status !== "refuse" && !["ongoing", "done"].includes(sig) && <Button size="sm" onClick={() => act(() => api.post(`/quotes/${q.id}/signature`), "Demande de signature envoyée au client")} data-testid={`quote-sign-${q.number}`}><PenLine />Faire signer</Button>}
        {sig === "ongoing" && <Button size="sm" onClick={() => act(() => api.post(`/quotes/${q.id}/signature/refresh`), "Statut de signature actualisé")} data-testid={`quote-sign-refresh-${q.number}`}><RefreshCw />Actualiser</Button>}
        {canQuote && sig === "ongoing" && <Button size="sm" variant="ghost" onClick={() => act(() => api.post(`/quotes/${q.id}/signature/cancel`), "Signature annulée")} data-testid={`quote-sign-cancel-${q.number}`}><XCircle />Annuler la signature</Button>}
        {q.signature?.signed_file && <Button size="sm" onClick={() => pdf(`/quotes/${q.id}/signed-pdf`, `${q.number}-signe`)} data-testid={`quote-signed-pdf-${q.number}`}><Download />Devis signé</Button>}
        {Q_OPEN.includes(q.status) && <QuoteStock q={q} onChanged={onChanged} />}
        <QuoteDocsButtons q={q} canQuote={canQuote} onChanged={onChanged} />
        {canQuote && <DuplicateButton q={q} onDone={onChanged} />}
        {canQuote && free && Q_OPEN.includes(q.status) && <Button size="sm" onClick={() => setEdit(true)} data-testid={`quote-edit-${q.number}`}><Pencil />Modifier</Button>}
        {canQuote && free && (
          <Select value={q.status} onValueChange={(v) => act(() => api.post(`/quotes/${q.id}/status`, { status: v }), "Statut du devis mis à jour")}>
            <SelectTrigger className="h-8 w-32 rounded-full text-xs" data-testid={`quote-status-select-${q.number}`}><SelectValue /></SelectTrigger>
            <SelectContent>{Object.entries(Q_STATUS).filter(([k]) => k !== "remplace").map(([k, l]) => <SelectItem key={k} value={k} data-testid={`quote-status-option-${k}`}>{l}</SelectItem>)}</SelectContent>
          </Select>
        )}
        {canInvoice && live && q.status !== "refuse" && !kinds.includes("solde") && (
          <>
            {!kinds.includes("acompte") && q.deposit_percent > 0 && <Button size="sm" onClick={() => bill("acompte")} data-testid={`quote-invoice-acompte-${q.number}`}><Receipt />Facture d'acompte</Button>}
            <Button size="sm" onClick={() => bill("solde")} data-testid={`quote-invoice-solde-${q.number}`}><Receipt />Facture de solde</Button>
          </>
        )}
      </div>
      {q.signature?.answers?.length > 0 && <div className="mt-4 rounded-2xl border border-border p-4 text-sm sm:ml-9" data-testid={`quote-answers-${q.number}`}>{q.signature.answers.map((a, i) => <div key={i}><span className="text-muted-foreground">{a.question} : </span><b>{a.answer}</b></div>)}</div>}
      {edit && <QuoteEditor quote={q} onOpenChange={setEdit} onSaved={onChanged} />}
    </div>
  );
}

export function InvoiceCard({ i, onChanged, showEvent = true }) {
  const { canInvoice } = useBillingPerms();
  const [pay, setPay] = useState(false);
  return (
    <div className="card-soft hover-lift p-6" data-testid={`invoice-card-${i.number}`}>
      <div className="flex gap-4">
        <div className="flex shrink-0 flex-col items-center gap-3"><Receipt className="mt-0.5 h-5 w-5" /><TrashBtn kind="invoice" id={i.id} name={i.number} onDone={onChanged} /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><span className="text-lg font-semibold">{i.number}</span><DocBadge status={i.status} label={I_STATUS[i.status]} testid={`invoice-status-${i.number}`} /></div>
          <div className="truncate text-sm text-muted-foreground">{i.kind.startsWith("avoir") ? "Avoir" : i.kind === "acompte" ? "Facture d'acompte" : "Facture de solde"}{i.credit_note_number ? ` · annulée par ${i.credit_note_number}` : ""} · devis {i.quote_number}{showEvent ? ` · ${i.event_title}` : ""}</div>
        </div>
        <div className="text-right"><div className="text-lg font-bold" data-testid={`invoice-ttc-${i.number}`}>{fmtEur2(i.total_ttc)}</div><div className="text-xs text-muted-foreground">TTC</div></div>
      </div>
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 sm:pl-9">
        <Meta icon={User}>{i.client?.name || "—"}</Meta>
        <Meta icon={Calendar}>Échéance {fmtDate(i.due_date)}</Meta>
        <Meta icon={Banknote} testid={`invoice-balance-${i.number}`}>Reste {fmtEur2(i.balance_due)}</Meta>
      </div>
      <div className="mt-5 flex flex-wrap gap-2 sm:pl-9">
        <Button size="sm" onClick={() => pdf(`/invoices/${i.id}/pdf`, i.number)} data-testid={`invoice-pdf-${i.number}`}><Download />PDF</Button>
        <Button size="sm" onClick={() => setPay(true)} data-testid={`invoice-payments-${i.number}`}><Banknote />Paiements ({i.payments.length})</Button>
        {canInvoice && i.status !== "annulee" && <Button size="sm" variant="outline" onClick={() => window.confirm(`Créer un avoir qui annule la facture ${i.number} ?`) && api.post(`/invoices/${i.id}/credit-note`).then((r) => { toast.success(`Avoir ${r.data.number} créé`); onChanged(); }).catch((e) => toast.error(errMsg(e)))} data-testid={`invoice-credit-${i.number}`}>Créer l'avoir</Button>}
      </div>
      {pay && <PaymentDialog invoice={i} write={canInvoice} onOpenChange={setPay} onSaved={onChanged} />}
    </div>
  );
}
