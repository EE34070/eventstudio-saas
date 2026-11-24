import { useCallback, useEffect, useState } from "react";
import { TrashBtn, BulkDelete } from "@/components/Trash";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Download, LayoutGrid, List, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SearchPill } from "@/components/common";
import { DocBadge, Q_STATUS, QuoteCard, useBillingPerms } from "@/components/billing/BillingParts";
import { QuoteEditor } from "@/components/billing/QuoteEditor";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { fmtDate, fmtEur2 } from "@/lib/constants";

const GROUPS = [["to_process", "À traiter"], ["accepted", "Acceptés"], ["closed", "Clos"], ["all", "Tous"]];
const QUICK = [["follow_up", "À relancer"], ["expiring", "Expire bientôt"], ["mine", "Mes devis"]];
const STATUSES = ["brouillon", "envoye", "vu", "negociation", "accepte", "refuse", "expire"];
const OPEN = ["brouillon", "envoye", "vu", "negociation"];
const COLS = [["number", "N°"], ["client", "Client"], ["event", "Événement"], ["event_date", "Date évén."], ["venue", "Lieu"], ["brand", "Marque"], ["total_ht", "Montant HT"], ["total_ttc", "Montant TTC"], ["status", "Statut"], ["sent_at", "Envoyé le"], ["valid_until", "Expiration"], ["last_activity", "Dernière activité"], ["owner", "Responsable"]];
const ADV = { event_id: "Événement", client_id: "Client", venue_id: "Lieu", owner_id: "Responsable", created_from: "Créé depuis", date_from: "Du", date_to: "Au", min_ht: "HT min", max_ht: "HT max", q: "Recherche" };
const KEY = "devis-liste";
const sel = "h-9 rounded-lg border border-border bg-card px-2 text-sm";

export function QuoteList({ quotes, invoices, reload }) {
  const { canQuote } = useBillingPerms();
  const [sp, setSp] = useSearchParams();
  const [d, setD] = useState(null);
  const [panel, setPanel] = useState(false);
  const [picked, setPicked] = useState([]);
  const [edit, setEdit] = useState(null);
  const [menu, setMenu] = useState("");
  const [mails, setMails] = useState(null);
  const [order, setOrder] = useState(() => JSON.parse(localStorage.getItem(`${KEY}-order`) || "[]"));
  const [hidden, setHidden] = useState(() => JSON.parse(localStorage.getItem(`${KEY}-cols`) || "[]"));
  const view = sp.get("view") || localStorage.getItem(`${KEY}-view`) || (window.innerWidth < 768 ? "cards" : "list");
  const qs = sp.toString();
  useEffect(() => { if (!qs && localStorage.getItem(KEY)) setSp(new URLSearchParams(localStorage.getItem(KEY)), { replace: true }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const load = useCallback(() => { const p = new URLSearchParams(qs); p.delete("view"); p.delete("tab"); return api.get(`/quote-list?${p}`).then((r) => setD(r.data)).catch((e) => toast.error(errMsg(e))); }, [qs]);
  useEffect(() => { const t = setTimeout(load, 200); localStorage.setItem(KEY, qs); return () => clearTimeout(t); }, [load, qs]);
  const set = (patch) => { const p = new URLSearchParams(sp); Object.entries(patch).forEach(([k, v]) => { p.delete(k); (Array.isArray(v) ? v : [v]).filter(Boolean).forEach((x) => p.append(k, x)); }); if (!("page" in patch)) p.delete("page"); setSp(p, { replace: true }); };
  const toggle = (k, v) => set({ [k]: sp.getAll(k).includes(v) ? sp.getAll(k).filter((x) => x !== v) : [...sp.getAll(k), v] });
  const changed = () => { load(); reload(); };
  if (!d) return null;
  const ordered = [...COLS].sort((a, b) => (order.indexOf(a[0]) + 1 || 99) - (order.indexOf(b[0]) + 1 || 99));
  const moveCol = (k, dir) => { const n = ordered.map(([x]) => x); const i = n.indexOf(k); if (i + dir < 0 || i + dir >= n.length) return; [n[i], n[i + dir]] = [n[i + dir], n[i]]; setOrder(n); localStorage.setItem(`${KEY}-order`, JSON.stringify(n)); };
  const remind = (send) => api.post("/quote-list/remind", { ids: picked, send }).then((r) => { setMails(r.data); if (send) { toast.success(`${r.data.filter((x) => x.sent).length} relance(s) envoyée(s)`); changed(); } }).catch((e) => toast.error(errMsg(e)));
  const cols = ordered.filter(([k]) => !hidden.includes(k) && (d.money || !k.startsWith("total_")));
  const sortBy = (k) => set({ sort: k, dir: sp.get("sort") === k && sp.get("dir") !== "desc" ? "desc" : "asc" });
  const openQ = (r) => (canQuote && OPEN.includes(r.status) ? setEdit(r) : api.post(`/quotes/${r.id}/share`).then((x) => window.open(`${window.location.origin}/devis/${x.data.token}?apercu=1`, "_blank", "noopener")).catch((e) => toast.error(errMsg(e))));
  const csv = () => { const p = new URLSearchParams(qs); p.delete("view"); p.delete("page"); if (picked.length) p.set("ids", picked.join(",")); api.get(`/quote-list/csv?${p}`, { responseType: "blob" }).then((r) => { const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = "devis.csv"; a.click(); }).catch((e) => toast.error(errMsg(e))); };
  const cell = (r, k) => ({ number: <b>{r.number}</b>, client: r.client || "—", event: r.event_id ? `${r.event_code} · ${r.event_title}` : "—", event_date: fmtDate(r.event_date) || "—", venue: r.venue || "—", total_ht: fmtEur2(r.total_ht), total_ttc: fmtEur2(r.total_ttc),
    status: <DocBadge status={r.status} label={Q_STATUS[r.status]} testid={`ql-status-${r.number}`} />, sent_at: fmtDate(r.sent_at) || "—", valid_until: <span className={r.expiring ? "font-semibold text-red-600" : ""}>{fmtDate(r.valid_until) || "—"}</span>, last_activity: fmtDate(r.last_activity) || "—", owner: r.owner || "—" })[k];
  const chips = [...sp.getAll("status").map((s) => ["status", s, Q_STATUS[s]]), ...Object.keys(ADV).filter((k) => sp.get(k)).map((k) => [k, sp.get(k), `${ADV[k]} : ${k === "event_id" ? quotes.find((x) => x.event_id === sp.get(k))?.event_title || "…" : k === "client_id" ? quotes.find((x) => x.client_id === sp.get(k))?.client?.name || "…" : k === "venue_id" ? d.venues.find((x) => x.id === sp.get(k))?.name : k === "owner_id" ? d.owners.find((x) => x.id === sp.get(k))?.name : sp.get(k)}`])];
  const opts = (k, label) => [...new Map(quotes.filter((x) => x[k]).map((x) => [x[k], label(x)])).entries()].sort((a, b) => String(a[1]).localeCompare(String(b[1])));
  const pages = Math.ceil(d.footer.count / d.size);
  const pill = (on) => `rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${on ? "border-foreground bg-foreground text-background" : "border-border text-muted-foreground hover:bg-secondary"}`;
  return (
    <div data-testid="quote-list">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {GROUPS.map(([k, l]) => <button key={k} className={pill(d.group === k)} onClick={() => set({ group: k, status: [], sort: "", dir: "" })} data-testid={`ql-group-${k}`}>{l} ({d.counts[k]})</button>)}
        {d.group === "custom" && <span className={pill(true)} data-testid="ql-group-custom">Personnalisé</span>}
        <span className="flex-1" />
        <div className="flex rounded-full border border-border p-1">{[["list", List, "Liste"], ["cards", LayoutGrid, "Cartes"]].map(([k, I, l]) => <button key={k} aria-label={l} className={`rounded-full px-3 py-1 ${view === k ? "bg-foreground text-background" : "text-muted-foreground"}`} onClick={() => { localStorage.setItem(`${KEY}-view`, k); set({ view: k, page: sp.get("page") || "" }); }} data-testid={`ql-view-${k}`}><I className="h-4 w-4" /></button>)}</div>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <SearchPill value={sp.get("q") || ""} onChange={(v) => set({ q: v })} placeholder="Numéro, client, événement, lieu…" testid="billing-search-input" />
        {QUICK.map(([k, l]) => <button key={k} className={pill(sp.getAll("quick").includes(k))} onClick={() => toggle("quick", k)} title={k === "follow_up" ? `Envoyé ou vu depuis plus de ${d.follow_up_days} jours sans réponse` : k === "expiring" ? "Date de validité dans moins de 7 jours" : "Événements dont vous êtes responsable"} data-testid={`ql-quick-${k}`}>{l}</button>)}
        <Button size="sm" variant="outline" onClick={() => setPanel(!panel)} data-testid="ql-filters-toggle"><SlidersHorizontal />Filtres</Button>
        {(chips.length > 0 || sp.getAll("quick").length > 0) && <button className="text-xs underline" onClick={() => setSp(new URLSearchParams({ group: sp.get("group") || "to_process" }), { replace: true })} data-testid="ql-reset">Réinitialiser</button>}
        <span className="flex-1" /><BulkDelete kind="quote" picked={picked} onDone={() => { setPicked([]); changed(); }} />{canQuote && picked.length > 0 && <Button size="sm" variant="outline" onClick={() => remind(false)} data-testid="ql-remind">Relancer ({picked.length})</Button>}<Button size="sm" variant="outline" onClick={csv} data-testid="ql-csv"><Download />CSV{picked.length ? ` (${picked.length})` : ""}</Button>
        {view === "list" && <div className="relative"><Button size="sm" variant="ghost" onClick={() => setMenu(menu === "cols" ? "" : "cols")} data-testid="ql-columns">Colonnes</Button>
          {menu === "cols" && <div className="absolute right-0 z-30 mt-1 w-52 rounded-xl border border-border bg-card p-2 text-sm shadow-lg">{ordered.filter(([k]) => d.money || !k.startsWith("total_")).map(([k, l]) => <label key={k} className="flex items-center gap-2 py-0.5"><button type="button" aria-label="Monter" onClick={(e) => { e.preventDefault(); moveCol(k, -1); }} data-testid={`ql-col-up-${k}`}>↑</button><button type="button" aria-label="Descendre" onClick={(e) => { e.preventDefault(); moveCol(k, 1); }}>↓</button><input type="checkbox" checked={!hidden.includes(k)} onChange={() => { const n = hidden.includes(k) ? hidden.filter((x) => x !== k) : [...hidden, k]; setHidden(n); localStorage.setItem(`${KEY}-cols`, JSON.stringify(n)); }} data-testid={`ql-col-${k}`} />{l}</label>)}</div>}</div>}
      </div>
      {chips.length > 0 && <div className="mb-3 flex flex-wrap gap-2" data-testid="ql-chips">{chips.map(([k, v, l]) => <button key={k + v} className="flex items-center gap-1 rounded-full bg-secondary px-2 py-1 text-xs" onClick={() => (k === "status" ? toggle("status", v) : set({ [k]: "" }))}>{l}<X className="h-3 w-3" /></button>)}</div>}
      {panel && <div className="mb-4 grid grid-cols-1 gap-3 rounded-2xl border border-border p-4 text-sm md:grid-cols-3" data-testid="ql-filters">
        <div className="md:col-span-3"><div className="mb-1 text-xs font-semibold text-muted-foreground">Statut (prend le pas sur l'onglet)</div><div className="flex flex-wrap gap-2">{STATUSES.map((s) => <button key={s} className={pill(sp.getAll("status").includes(s))} onClick={() => toggle("status", s)} data-testid={`ql-status-filter-${s}`}>{Q_STATUS[s]}</button>)}</div></div>
        <label className="text-xs text-muted-foreground">Période sur<select className={`${sel} mt-1 w-full`} value={sp.get("period") || "event"} onChange={(e) => set({ period: e.target.value })} data-testid="ql-period"><option value="event">Date de l'événement</option><option value="created">Date de création</option><option value="sent">Date d'envoi</option></select></label>
        <label className="text-xs text-muted-foreground">Du<Input className="mt-1 h-9" type="date" value={sp.get("date_from") || ""} onChange={(e) => set({ date_from: e.target.value })} data-testid="ql-date-from" /></label>
        <label className="text-xs text-muted-foreground">Au<Input className="mt-1 h-9" type="date" value={sp.get("date_to") || ""} onChange={(e) => set({ date_to: e.target.value })} data-testid="ql-date-to" /></label>
        {[["client_id", "Client", opts("client_id", (x) => x.client?.name || "—")], ["event_id", "Événement", opts("event_id", (x) => `${x.event_code || ""} · ${x.event_title || ""}`)], ["venue_id", "Lieu", d.venues.map((x) => [x.id, x.name])], ["owner_id", "Responsable", d.owners.map((x) => [x.id, x.name])],
          ["created_from", "Créé depuis", [["devis", "Devis"], ["evenement", "Événement"], ["crm", "CRM"], ["import", "Import"]]]].map(([k, l, o]) => <label key={k} className="text-xs text-muted-foreground">{l}<select className={`${sel} mt-1 w-full`} value={sp.get(k) || ""} onChange={(e) => set({ [k]: e.target.value })} data-testid={`ql-filter-${k}`}><option value="">Tous</option>{o.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select></label>)}
        {d.money && [["min_ht", "Montant HT min"], ["max_ht", "Montant HT max"]].map(([k, l]) => <label key={k} className="text-xs text-muted-foreground">{l}<Input className="mt-1 h-9" type="number" min="0" value={sp.get(k) || ""} onChange={(e) => set({ [k]: e.target.value })} data-testid={`ql-${k}`} /></label>)}
      </div>}
      {!d.rows.length ? <p className="py-10 text-center text-sm text-muted-foreground" data-testid="ql-empty">Aucun devis ne correspond.</p> : view === "cards" ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="billing-list-devis">{d.rows.map((r) => { const q = quotes.find((x) => x.id === r.id); return q ? <div key={r.id} data-testid={`billing-quote-${r.number}`}><QuoteCard q={q} invoices={invoices} onChanged={changed} /></div> : null; })}</div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-border"><table className="w-full text-sm" data-testid="ql-table">
          <thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="p-2"><input type="checkbox" aria-label="Tout sélectionner" checked={picked.length > 0 && d.rows.every((r) => picked.includes(r.id))} onChange={(e) => setPicked(e.target.checked ? d.rows.map((r) => r.id) : [])} data-testid="ql-pick-all" /></th>
            {cols.map(([k, l]) => <th key={k} className="cursor-pointer whitespace-nowrap p-2" onClick={() => sortBy(k)} data-testid={`ql-sort-${k}`}>{l}{sp.get("sort") === k ? (sp.get("dir") === "desc" ? " ↓" : " ↑") : ""}</th>)}<th className="p-2" /></tr></thead>
          <tbody>{d.rows.map((r) => (
            <tr key={r.id} className="cursor-pointer border-b border-border last:border-0 hover:bg-secondary/50" onClick={() => openQ(r)} data-testid={`ql-row-${r.number}`}>
              <td className="p-2" onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Sélectionner ${r.number}`} checked={picked.includes(r.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, r.id] : picked.filter((x) => x !== r.id))} data-testid={`ql-pick-${r.number}`} /></td>
              {cols.map(([k]) => <td key={k} className={`whitespace-nowrap p-2 ${k.startsWith("total_") ? "text-right" : ""}`}>{cell(r, k)}</td>)}
              <td className="relative whitespace-nowrap p-2" onClick={(e) => e.stopPropagation()}><TrashBtn kind="quote" id={r.id} name={r.number} onDone={changed} /><button aria-label="Actions" className="px-2 font-bold" onClick={() => setMenu(menu === r.id ? "" : r.id)} data-testid={`ql-actions-${r.number}`}>⋯</button>
                {menu === r.id && <div className="absolute right-2 z-30 w-44 rounded-xl border border-border bg-card p-1 text-left shadow-lg" onClick={() => setMenu("")}>
                  <button className="block w-full rounded px-2 py-1 text-left hover:bg-secondary" onClick={() => openQ(r)}>Ouvrir</button>
                  <button className="block w-full rounded px-2 py-1 text-left hover:bg-secondary" onClick={() => downloadPdf(`/quotes/${r.id}/pdf`, `${r.number}.pdf`).catch(() => toast.error("Impossible de générer le PDF"))}>PDF</button>
                  {canQuote && OPEN.includes(r.status) && <button className="block w-full rounded px-2 py-1 text-left hover:bg-secondary" onClick={() => api.post(`/quotes/${r.id}/status`, { status: "accepte" }).then(() => { toast.success(`Devis ${r.number} accepté`); changed(); }).catch((e) => toast.error(errMsg(e)))} data-testid={`ql-accept-${r.number}`}>Marquer accepté</button>}
                  {r.event_id && <Link className="block rounded px-2 py-1 hover:bg-secondary" to={`/evenements/${r.event_id}?tab=devis`}>Ouvrir l'événement</Link>}
                  <button className="block w-full rounded px-2 py-1 text-left hover:bg-secondary" onClick={() => set({ view: "cards", q: r.number })}>Dupliquer, envoyer… (carte)</button></div>}</td>
            </tr>))}</tbody></table></div>)}
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm" data-testid="ql-footer"><span data-testid="billing-count">{d.footer.count} devis</span>{d.footer.total_ht != null && <span>· total HT <b data-testid="ql-total-ht">{fmtEur2(d.footer.total_ht)}</b></span>}<span className="flex-1" />
        {pages > 1 && <><Button size="sm" variant="outline" disabled={d.page <= 1} onClick={() => set({ page: String(d.page - 1) })} data-testid="ql-prev">Précédent</Button><span>{d.page} / {pages}</span><Button size="sm" variant="outline" disabled={d.page >= pages} onClick={() => set({ page: String(d.page + 1) })} data-testid="ql-next">Suivant</Button></>}</div>
      {mails && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" data-testid="ql-remind-dialog"><div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-card p-5">
        <div className="mb-3 font-display text-lg">Relance groupée — aperçu des e-mails</div>
        {mails.map((m) => <div key={m.id} className={`mb-3 rounded-xl border border-border p-3 text-sm ${m.ok ? "" : "opacity-60"}`} data-testid={`ql-remind-${m.number}`}><b>{m.number}</b> → {m.to || "—"}{m.sent && <span className="ml-2 text-emerald-600">envoyé</span>}{m.why && <span className="ml-2 text-red-600">{m.why}</span>}<div className="mt-1 font-semibold">{m.subject}</div>{m.body.map((p, i) => <p key={i} className="text-muted-foreground">{p}</p>)}</div>)}
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setMails(null)}>Fermer</Button><Button disabled={!mails.some((m) => m.ok && !m.sent)} onClick={() => remind(true)} data-testid="ql-remind-send">Envoyer {mails.filter((m) => m.ok && !m.sent).length} relance(s)</Button></div></div></div>}
      {edit && <QuoteEditor quote={edit} onOpenChange={() => setEdit(null)} onSaved={changed} />}
    </div>);
}
