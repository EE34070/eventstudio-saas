import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Link2, FileText, Unlink, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Section } from "@/components/common";
import { DocBadge, Q_STATUS, useBillingPerms } from "@/components/billing/BillingParts";
import { DuplicateButton } from "@/components/billing/DuplicateQuote";
import { QuoteEditor } from "@/components/billing/QuoteEditor";
import { MatchDialog } from "@/components/billing/MatchDialog";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { fmtEur2, fmtDate } from "@/lib/constants";
import { useMe } from "@/context/MeContext";

const ko = (e) => toast.error(errMsg(e));
const OPEN = ["brouillon", "envoye", "vu", "negociation"];
const DIFF = { client: "client différent", dates: "dates différentes" };

function AttachDialog({ ev, onClose, onDone }) {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const [rows, setRows] = useState([]);
  const [picked, setPicked] = useState([]);
  const [align, setAlign] = useState("quote");
  useEffect(() => { const t = setTimeout(() => api.get(`/events/${ev.id}/quote-candidates`, { params: { q, all } }).then((r) => setRows(r.data)).catch(ko), 250); return () => clearTimeout(t); }, [ev.id, q, all]);
  const sel = rows.filter((r) => picked.includes(r.id));
  const submit = async () => {
    const moved = sel.filter((r) => r.event_id);
    if (moved.length && !window.confirm(`${moved.map((r) => `${r.number} est lié à ${r.event_label}`).join("\n")}\n\nDéplacer vers ${ev.code} ?`)) return;
    try { await api.post(`/events/${ev.id}/quotes/attach`, { quote_ids: picked, confirm_move: moved.length > 0, align }); toast.success(`${picked.length} devis rattaché(s)`); onDone(); onClose(); } catch (e) { ko(e); }
  };
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto" data-testid="attach-quote-dialog">
        <DialogHeader><DialogTitle className="text-xl font-bold">Rattacher un devis existant</DialogTitle></DialogHeader>
        <Input placeholder="N°, client, montant, date…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="attach-search" />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} data-testid="attach-all" />Afficher tous les devis (par défaut : sans événement ou même client)</label>
        <div className="divide-y divide-border text-sm" data-testid="attach-list">
          {!rows.length && <p className="py-4 text-muted-foreground">Aucun devis trouvé.</p>}
          {rows.map((r) => (
            <label key={r.id} className="flex cursor-pointer items-start gap-3 py-2.5" data-testid={`attach-row-${r.number}`}>
              <input type="checkbox" className="mt-1" checked={picked.includes(r.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, r.id] : picked.filter((x) => x !== r.id))} data-testid={`attach-pick-${r.number}`} />
              <span className="min-w-0 flex-1"><b>{r.number}</b> V{r.version} · {r.client || "sans client"} · {fmtDate(r.date)} · {Q_STATUS[r.status]}
                {r.event_id && <span className="block text-xs font-semibold text-amber-600">lié à {r.event_label}</span>}
                {r.diffs.length > 0 && <span className="block text-xs text-amber-600">{r.diffs.map((d) => DIFF[d]).join(", ")}{r.signed ? " — devis signé : il ne sera pas modifié" : ""}</span>}</span>
              <span className="font-semibold">{fmtEur2(r.total_ttc)}</span>
            </label>
          ))}
        </div>
        {sel.some((r) => r.diffs.length && !r.signed) && (
          <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="attach-align">
            <div className="font-semibold">Client ou dates différents de l'événement</div>
            <label className="mt-1 flex items-center gap-2"><input type="radio" checked={align === "quote"} onChange={() => setAlign("quote")} data-testid="attach-align-quote" />Garder les valeurs du devis</label>
            <label className="flex items-center gap-2"><input type="radio" checked={align === "event"} onChange={() => setAlign("event")} data-testid="attach-align-event" />Aligner le devis sur l'événement (client, langue, dates)</label>
          </div>
        )}
        <DialogFooter><Button disabled={!picked.length} onClick={submit} data-testid="attach-submit"><Link2 />Rattacher {picked.length || ""}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function DevisTab({ ev, quotes, reloadQuotes, reload }) {
  const { can } = useMe();
  const { canQuote } = useBillingPerms();
  const money = can("finance:read");
  const [open, setOpen] = useState("");
  const [edit, setEdit] = useState(null);
  const [match, setMatch] = useState("");
  const recalc = () => api.post(`/events/${ev.id}/recalc-quotes`).then((r) => { toast.success(r.data.quote ? `Événement recalculé depuis le devis ${r.data.quote}` : "Aucun devis : montants remis à zéro"); changed(); }).catch(ko);
  const changed = () => { reloadQuotes(); reload(); };
  const link = (q) => api.post(`/quotes/${q.id}/share`).then((r) => { const url = `${window.location.origin}/devis/${r.data.token}`; navigator.clipboard?.writeText(url).catch(() => {}); toast.success("Lien client copié"); return url; });
  const openQ = (q) => (canQuote && OPEN.includes(q.status) && !q.signed ? setEdit(q) : link(q).then((url) => window.open(`${url}?apercu=1`, "_blank", "noopener")).catch(ko));
  const detach = async (q) => { if (!window.confirm(`Détacher le devis ${q.number} de cet événement ? Il reste disponible dans Devis & factures.`)) return; try { await api.post(`/quotes/${q.id}/detach`); toast.success("Devis détaché"); changed(); } catch (e) { ko(e); } };
  const buttons = canQuote && <><Button size="sm" onClick={() => api.post(`/events/${ev.id}/quotes`).then((r) => { toast.success(`Devis ${r.data.number} créé`); changed(); setEdit(r.data); }).catch(ko)} data-testid="event-new-quote"><Plus />Nouveau devis</Button><Button size="sm" variant="outline" onClick={() => setOpen("attach")} data-testid="event-attach-quote"><Link2 />Rattacher un devis existant</Button></>;
  return (
    <Section title="Devis" testid="event-quotes-tab" actions={quotes?.length > 0 && <>{canQuote && <Button size="sm" variant="ghost" onClick={recalc} data-testid="event-recalc-quotes">Recalculer depuis les devis</Button>}{buttons}</>}>
      {(quotes || []).some((q) => q.flat) && <div className="mb-3 rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="event-quote-flat-banner">Matériel à saisir — devis importé sans détail : ajoutez les articles à la main dans l'onglet Matériel.</div>}
      {quotes && !quotes.length && <div className="py-6 text-center" data-testid="event-quotes-empty"><p className="mb-4 text-sm text-muted-foreground">Aucun devis pour cet événement</p><div className="flex flex-wrap justify-center gap-2">{buttons}</div></div>}
      <div className="divide-y divide-border">
        {(quotes || []).map((q) => (
          <div key={q.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 text-sm" data-testid={`event-quote-${q.number}`}>
            <span className="font-semibold">{q.number}</span><span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-semibold">V{q.version}</span><DocBadge status={q.status} label={Q_STATUS[q.status]} testid={`event-quote-status-${q.number}`} />
            <span className="text-muted-foreground">{fmtDate(q.date)}</span>
            {q.total_ttc != null && <span data-testid={`event-quote-total-${q.number}`}>{fmtEur2(q.total_ht)} HT · <b>{fmtEur2(q.total_ttc)} TTC</b></span>}
            {q.imported && <span className="rounded-full bg-secondary px-2 py-0.5 text-xs">Importé</span>}
            {q.unmatched > 0 && <button type="button" className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-semibold text-amber-700" onClick={() => setMatch(q.id)} data-testid={`event-quote-unmatched-${q.number}`}>Matériel non rapproché ({q.unmatched})</button>}
            {q.imported && !q.flat && !q.unmatched && canQuote && <button type="button" className="text-xs underline" onClick={() => setMatch(q.id)} data-testid={`event-quote-matching-${q.number}`}>Correspondances</button>}
            {q.import_gap ? <span className="text-xs font-semibold text-red-600" data-testid={`event-quote-gap-${q.number}`}>Écart avec le total importé : {fmtEur2(q.import_gap)}</span> : null}
            <span className="ml-auto" />
            {money && <><Button size="sm" variant="outline" onClick={() => openQ(q)} data-testid={`event-quote-open-${q.number}`}><ExternalLink />Ouvrir</Button>
              <Button size="sm" variant="outline" onClick={() => downloadPdf(`/quotes/${q.id}/pdf`, `${q.number}.pdf`).catch(() => toast.error("Impossible de générer le PDF"))} data-testid={`event-quote-pdf-${q.number}`}><FileText />PDF</Button>
              <Button size="sm" variant="outline" onClick={() => link(q).catch(ko)} data-testid={`event-quote-link-${q.number}`}><Link2 />Lien client</Button></>}
            {canQuote && <DuplicateButton q={{ ...q, event_id: ev.id, event_title: ev.title }} onDone={changed} />}
            {canQuote && <Button size="sm" variant="ghost" onClick={() => detach(q)} data-testid={`event-quote-detach-${q.number}`}><Unlink />Détacher</Button>}
          </div>
        ))}
      </div>
      {open === "attach" && <AttachDialog ev={ev} onClose={() => setOpen("")} onDone={changed} />}
      {match && <MatchDialog quoteId={match} onClose={() => setMatch("")} onDone={changed} />}
      {edit && <QuoteEditor quote={edit} onOpenChange={() => setEdit(null)} onSaved={changed} />}
    </Section>
  );
}
