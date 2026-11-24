import { useEffect, useRef, useState } from "react";
import { useMe } from "@/context/MeContext";
import { LogisticsPanel, linesOf } from "@/components/billing/LogisticsPanel";
import { PackLine, packOf } from "@/components/billing/PackParts";
import { TranslationAlert } from "@/components/catalogue/PackI18n";
import { TitleTranslations } from "@/components/events/TitleTranslations";
import { ReuseBanner, ReuseLine, UsageHours } from "@/components/billing/ReuseParts";
import { DjQuoteBox } from "@/components/dj/DjPlanning";
import { NewProduct } from "@/components/billing/NewProduct";
import { QuickAdd } from "@/components/billing/QuickAdd";
import { toast } from "sonner";
import { Plus, Trash2, ArrowUp, ArrowDown, Copy, GripVertical, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { QuoteMaterial } from "@/components/catalogue/Material";
import { dual, toPieces, uomLabel, uomOf } from "@/components/catalogue/Units";
import { Field } from "@/components/common";
import { DuplicateButton } from "@/components/billing/DuplicateQuote";
import { api, errMsg, downloadPdf } from "@/lib/api";
import { fmtEur2 } from "@/lib/constants";
import { SupplierImport, SupplierQuotes } from "@/components/billing/SupplierImport";

const ko = (e) => toast.error(errMsg(e));
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
const sel = "h-9 rounded-lg border border-border bg-background px-2 text-xs";
const MODES = [["detailed", "Détaillé"], ["section_totals", "Total par section"], ["total_only", "Total global seul"], ["none", "Sans prix (non contractuel)"]];
const blank = (type, parent_id) => ({ id: uid(), parent_id, type, title: type === "section" ? "Nouvelle section" : type === "subsection" ? "Nouvelle sous-section" : "", description: "", space_id: "", show_subtotal: true, optional: false, selected: false, price_display_override: "", discount_percent: 0, label: "", qty: 1, unit_price: 0, vat: 20, equipment_id: "", pack_id: "", kind: "service", unit: "" });

export function PublicRows({ q, eur, n, lang, onToggle }) {
  return (
    <div className="card-soft mt-4 divide-y divide-border px-6" data-testid="public-quote-rows">
      {q.dates_lines?.length > 0 && <div className="py-3 text-sm text-muted-foreground" data-testid="public-quote-dates">{q.dates_lines.map((d) => <div key={d}>{d}</div>)}</div>}
      {q.client_modified && <div className="py-3 text-sm font-semibold text-amber-600" data-testid="public-quote-modified">{lang === "fr" ? "Devis modifié par vos soins : en attente de validation." : "Quote modified by you: awaiting validation."}</div>}
      {q.rows.map((r, i) => r.kind === "title" ? (
        <div key={i} className={`flex items-center gap-3 py-3 ${r.level === 1 ? "text-base font-bold" : "pl-3 text-sm font-semibold"}`} data-testid={`public-section-${r.id}`}>
          {r.optional && <input type="checkbox" className="h-5 w-5" disabled={!q.can_choose} checked={r.selected} onChange={(e) => onToggle(r.id, e.target.checked)} aria-label={r.label} data-testid={`public-option-${r.id}`} />}<span>{r.label}</span>
        </div>
      ) : r.kind === "text" ? <div key={i} className="whitespace-pre-line py-2 text-sm text-muted-foreground">{r.label}</div>
        : r.kind === "subtotal" ? <div key={i} className="flex justify-between py-3 text-sm font-semibold" data-testid="public-subtotal"><span>{r.label}</span><span>{eur(r.amount)}</span></div>
          : (
            <div key={i} className="flex gap-4 py-3 pl-3" data-testid="public-row-line">
              <div className="min-w-0 flex-1"><div className="font-medium">{n(r.qty)} × {r.label}</div>{r.description && <div className="text-sm text-muted-foreground">{r.description}</div>}</div>
              {!r.hide_price && <div className="text-right text-sm"><div className="font-semibold">{eur(r.qty * r.unit_price)}</div><div className="text-xs text-muted-foreground">{eur(r.unit_price)} HT</div></div>}
            </div>
          ))}
    </div>
  );
}

function Dates({ d, set }) {
  const up = (k, patch) => set({ ...d, [k]: { ...d[k], ...patch } });
  const slot = (k, label, same, sameLabel) => (
    <div className="flex flex-wrap items-center gap-2 text-sm" data-testid={`dates-${k}`}>
      <label className="flex w-44 items-center gap-2 font-medium"><input type="checkbox" checked={d[k].enabled} onChange={(e) => up(k, { enabled: e.target.checked })} data-testid={`dates-${k}-enabled`} />{label}</label>
      {d[k].enabled && <><Input type="date" className="h-9 w-40" disabled={d[same]} value={d[same] ? (k === "delivery" ? d.operation.start : d.operation.end).slice(0, 10) : d[k].date} onChange={(e) => up(k, { date: e.target.value })} data-testid={`dates-${k}-date`} />
        <Input type="time" className="h-9 w-28" value={d[k].start} onChange={(e) => up(k, { start: e.target.value })} data-testid={`dates-${k}-start`} /><span>–</span><Input type="time" className="h-9 w-28" value={d[k].end} onChange={(e) => up(k, { end: e.target.value })} data-testid={`dates-${k}-end`} />
        <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={d[same]} onChange={(e) => set({ ...d, [same]: e.target.checked })} data-testid={`dates-${same}`} />{sameLabel}</label></>}
    </div>
  );
  return (
    <div className="space-y-2 rounded-2xl border border-border p-3" data-testid="quote-dates">
      <div className="text-sm font-semibold">Dates</div>
      {slot("delivery", "Livraison / installation", "delivery_same_day", "le jour de l'exploitation")}
      <div className="flex flex-wrap items-center gap-2 text-sm"><span className="w-44 font-medium">Exploitation</span><Input type="datetime-local" className="h-9 w-56" value={d.operation.start} onChange={(e) => up("operation", { start: e.target.value })} data-testid="dates-operation-start" /><span>→</span><Input type="datetime-local" className="h-9 w-56" value={d.operation.end} onChange={(e) => up("operation", { end: e.target.value })} data-testid="dates-operation-end" /></div>
      {slot("pickup", "Retrait / démontage", "pickup_after_operation", "à l'issue de l'exploitation")}
    </div>
  );
}

export function QuoteEditor({ quote, onOpenChange, onSaved }) {
  const [f, setF] = useState(null);
  const [eqs, setEqs] = useState([]);
  const [evs, setEvs] = useState([]);
  const [evText, setEvText] = useState("");
  const [imp, setImp] = useState(null);
  const reload = () => api.get(`/quotes/${quote.id}/structure`).then((r) => { setF(r.data); onSaved(); }).catch(ko);
  useEffect(() => { api.get("/events").then((r) => setEvs(r.data)).catch(() => {}); }, []);
  useEffect(() => { api.get(`/quotes/${quote.id}/structure`).then((r) => { setF(r.data); setEvText(r.data.event_label || ""); }).catch(ko); api.get("/equipment").then((r) => setEqs(r.data.items || [])).catch(() => {}); }, [quote.id]);
  const { can } = useMe();
  const [active, setActive] = useState("");
  const [np, setNp] = useState(null);
  const top = useRef(null);
  useEffect(() => {
    const key = (e) => { const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
      if (((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") || (e.key === "/" && !typing)) { e.preventDefault(); e.stopImmediatePropagation(); top.current?.focus(); } };
    document.addEventListener("keydown", key, true);
    return () => document.removeEventListener("keydown", key, true);
  }, []);
  const [logi, setLogi] = useState(false);
  const [gen, setGen] = useState(null);
  const eqKey = f ? JSON.stringify([linesOf(f.blocks), f.dates]) : "";
  useEffect(() => {
    if (!f?.has_trips) return undefined;
    const t = setTimeout(() => api.post(`/quotes/${quote.id}/trips/compute`, { lines: linesOf(f.blocks), dates: f.dates }).then((r) => setGen(r.data.lines)).catch(() => {}), 700);
    return () => clearTimeout(t);
  }, [eqKey, f?.has_trips, quote.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!f) return null;
  const B = f.blocks;
  const setB = (blocks) => setF({ ...f, blocks });
  const kids = (pid) => B.filter((b) => b.parent_id === pid);
  const upd = (id, patch) => setB(B.map((b) => (b.id === id ? { ...b, ...patch } : b)));
  const tree = (id) => [id, ...kids(id).flatMap((c) => tree(c.id))];
  const del = (id) => { const ids = tree(id); setB(B.filter((b) => !ids.includes(b.id))); };
  const move = (id, dir) => { const b = B.find((x) => x.id === id); const sib = B.filter((x) => x.parent_id === b.parent_id && (b.type === "section" ? x.type === "section" : true)); const j = sib.indexOf(b) + dir; if (j < 0 || j >= sib.length) return; const a = B.indexOf(b); const c = B.indexOf(sib[j]); const next = [...B]; [next[a], next[c]] = [next[c], next[a]]; setB(next); };
  const moveTo = (id, parent_id) => { const b = B.find((x) => x.id === id); const p = B.find((x) => x.id === parent_id); if (!b || !p || b.id === parent_id || b.parent_id === parent_id) return; if (b.type === "subsection" && p.type !== "section") return; if (b.type === "section") return; setB([...B.filter((x) => x.id !== id), { ...b, parent_id }]); };
  const clone = (id, keepParent = true) => { const ids = tree(id); const map = Object.fromEntries(ids.map((i) => [i, uid()])); return B.filter((b) => ids.includes(b.id)).map((b) => ({ ...b, id: map[b.id], parent_id: b.id === id ? (keepParent ? b.parent_id : "") : map[b.parent_id] })); };
  const price = (b) => { let p = b.unit_price * (1 - (b.discount_percent || 0) / 100) * (1 - (f.global_discount_percent || 0) / 100); let cur = B.find((x) => x.id === b.parent_id); let on = true; while (cur) { p *= 1 - (cur.discount_percent || 0) / 100; if (cur.optional && !cur.selected) on = false; cur = B.find((x) => x.id === cur.parent_id); } return [p, on]; };
  const sub = (id) => tree(id).map((i) => B.find((b) => b.id === i)).filter((b) => b.type === "line").reduce((n, b) => n + b.qty * price(b)[0], 0);
  const counted = B.filter((b) => b.type === "line" && price(b)[1]);
  const ht = counted.reduce((n, b) => n + b.qty * price(b)[0], 0);
  const vat = counted.reduce((n, b) => n + (b.qty * price(b)[0] * b.vat) / 100, 0);
  const targets = B.filter((b) => b.type === "section" || b.type === "subsection");
  const newSpace = async (id) => { const name = window.prompt("Nom du nouvel espace (enregistré sur le lieu)"); if (!name) return; try { const { data } = await api.post(`/venues/${f.venue_id}/spaces`, { name }); setF((x) => ({ ...x, spaces: [...x.spaces, data], blocks: x.blocks.map((b) => (b.id === id ? { ...b, space_id: data.id } : b)) })); } catch (e) { ko(e); } };
  const num = (v) => Number(v) || 0;
  const addCatalog = (pid, it, qty) => { const m = eqs.find((x) => x.id === it.id) || it; const same = kids(pid).find((x) => x.type === "line" && x.equipment_id === it.id);
    setB(same ? B.map((x) => (x.id === same.id ? { ...x, qty: num(x.qty) + qty } : x)) : [...B, { ...blank("line", pid), label: m.name, equipment_id: m.id, kind: "catalog", unit_price: it.price ?? 0, ...uomOf(m, m.quote_uom === "secondary" ? "secondary" : ""), qty, ...packOf(m, eqs) }]); toast.success(same ? `Quantité augmentée : ${m.name}` : `Ajouté : ${m.name}`); };
  const addFree = (pid, label, qty, price) => { setB([...B, { ...blank("line", pid), label, qty, unit_price: price ?? 0 }]); toast.success(`Prestation libre ajoutée : ${label}`); };
  const quick = (pid, testid, ref) => <QuickAdd eventId={f.event_id} testid={testid} inputRef={ref} canCreate={can("catalog:write")} onAdd={(it, qty) => addCatalog(pid, it, qty)} onFree={(label, qty, price) => addFree(pid, label, qty, price)} onCreate={(name, qty, price) => setNp({ pid, name, qty, price })} />;
  const activeId = targets.some((t) => t.id === active) ? active : targets[0]?.id;
  const isTrip = (b) => b.type === "line" && !!b.source_type;
  const mergeTrips = (blocks, g) => {
    let pid = blocks.find(isTrip)?.parent_id || blocks.find((b) => b.type === "section" && b.title === f.logistics_section)?.id;
    let out = blocks.filter((b) => !isTrip(b) || g.some((x) => x.source_id === b.source_id));
    if (!g.length) return out;
    if (!pid) { const s = { ...blank("section", ""), title: f.logistics_section }; pid = s.id; out = [...out, s]; }
    out = out.map((b) => { const x = isTrip(b) && g.find((y) => y.source_id === b.source_id); return x ? { ...b, label: x.label, unit_cost: x.unit_cost ?? b.unit_cost, ...(b.price_locked ? {} : { unit_price: x.unit_price }) } : b; });
    return [...out, ...g.filter((x) => !out.some((b) => isTrip(b) && b.source_id === x.source_id)).map((x) => ({ ...blank("line", pid), ...x }))];
  };
  const tripDiff = !gen ? [] : [...gen.flatMap((x) => { const b = B.find((y) => isTrip(y) && y.source_id === x.source_id); return !b ? [`+ ${x.label} : ${fmtEur2(x.unit_price)}`] : !b.price_locked && Math.abs(num(b.unit_price) - x.unit_price) > 0.005 ? [`${x.label} : ${fmtEur2(num(b.unit_price))} → ${fmtEur2(x.unit_price)}`] : b.label !== x.label ? [`${b.label} → ${x.label}`] : []; }),
    ...B.filter((b) => isTrip(b) && !gen.some((x) => x.source_id === b.source_id)).map((b) => `− ${b.label}`)];
  const byKind = [["Produits", (b) => b.equipment_id || b.pack_id], ["Transport", (b) => b.kind === "transport"], ["Main-d'œuvre", (b) => b.kind === "labor"], ["Frais de mission", (b) => b.kind === "expense"], ["Autres", (b) => !b.equipment_id && !b.pack_id && !["transport", "labor", "expense"].includes(b.kind)]];
  const costed = B.filter((b) => b.type === "line" && b.unit_cost > 0);
  const costTotal = counted.reduce((n, b) => n + b.qty * (b.unit_cost || 0), 0);
  const costedHt = counted.filter((b) => b.unit_cost > 0).reduce((n, b) => n + b.qty * price(b)[0], 0);
  const round = (p) => { const r = f.margin_rules?.rounding; return r ? Math.ceil(p / r - 1e-9) * r : Math.round(p * 100) / 100; };
  const bulk = (ids) => { const v = window.prompt("Coefficient sur coût (ex. 1,3) ou taux de marque avec % (ex. 30%)", "1,3"); if (!v) return; const x = num(v.replace("%", "").replace(",", ".")); if (!x) return; setB(B.map((b) => (ids.includes(b.id) && b.type === "line" && b.unit_cost > 0 ? { ...b, unit_price: round(v.includes("%") ? b.unit_cost / Math.max(1 - x / 100, 0.01) : b.unit_cost * x) } : b))); };
  const Margin = ({ b }) => { const c = b.unit_cost, p = num(b.unit_price), pending = p <= c + 0.001; return (
    <div className="col-span-12 flex flex-wrap items-center gap-2 rounded-lg bg-secondary/50 px-2 py-1 text-xs" data-testid={`line-margin-${b.id}`}>
      <span>Coût HT {fmtEur2(c)}</span>
      <label className="flex items-center gap-1">Coef.<Input type="number" step="any" className="h-7 w-20 text-xs" value={c ? Math.round((p / c) * 1000) / 1000 : ""} onChange={(e) => upd(b.id, { unit_price: Math.round(c * num(e.target.value) * 100) / 100 })} data-testid={`line-coef-${b.id}`} /></label>
      <label className="flex items-center gap-1">Marge %<Input type="number" step="any" className="h-7 w-20 text-xs" value={p ? Math.round(((p - c) / p) * 1000) / 10 : ""} onChange={(e) => upd(b.id, { unit_price: Math.round((c / Math.max(1 - num(e.target.value) / 100, 0.01)) * 100) / 100 })} data-testid={`line-markup-${b.id}`} /></label>
      <span>Marge {fmtEur2((p - c) * b.qty)}</span>
      {pending ? <span className="rounded-full bg-amber-500/20 px-2 py-0.5 font-semibold text-amber-700" data-testid={`line-margin-pending-${b.id}`}>Marge à définir</span> : p && ((p - c) / p) * 100 < (f.margin_rules?.min_percent ?? 0) ? <span className="font-semibold text-red-600">Sous le seuil de marge</span> : null}
      {b.detail && <span className="text-muted-foreground" title={b.detail.map((x) => `${x.qty} × ${x.label} (${x.unit_cost} €)`).join("\n")}>Forfait : {b.detail.length} ligne(s) internes</span>}
    </div>); };
  const relink = async (text) => {
    const e = evs.find((x) => `${x.code} · ${x.title}` === text);
    if (text && !e) return setEvText(f.event_label || "");
    if ((e?.id || "") === (f.event_id || "")) return undefined;
    if (!window.confirm(e ? `Rattacher ce devis à ${text} ?${f.event_id ? ` Il sera retiré de ${f.event_label}.` : ""}` : `Détacher ce devis de ${f.event_label} ?`)) return setEvText(f.event_label || "");
    try {
      await (e ? api.post(`/events/${e.id}/quotes/attach`, { quote_ids: [quote.id], confirm_move: true, align: "quote" }) : api.post(`/quotes/${quote.id}/detach`));
      const { data } = await api.get(`/quotes/${quote.id}/structure`);
      setF((x) => ({ ...x, event_id: data.event_id, event_label: data.event_label, event_dates: data.event_dates, dates: data.dates, spaces: data.spaces, venue_id: data.venue_id }));
      setEvText(data.event_label || ""); toast.success(e ? "Devis rattaché à l'événement" : "Devis détaché"); onSaved();
    } catch (err) { ko(err); setEvText(f.event_label || ""); }
    return undefined;
  };
  const save = async (e) => {
    e.preventDefault();
    const changed = f.dates && f.event_dates && JSON.stringify([f.dates.delivery, f.dates.operation, f.dates.pickup]) !== JSON.stringify([f.event_dates.delivery, f.event_dates.operation, f.event_dates.pickup]);
    if (changed && !window.confirm("Les dates du devis diffèrent de celles de l'événement : l'événement, la réservation du stock et les missions de livraison / retrait seront mis à jour. Continuer ?")) return;
    const body = { blocks: B.map((b) => ({ ...b, qty: num(b.qty) || 1, unit_price: num(b.unit_price), vat: num(b.vat), discount_percent: num(b.discount_percent) })), dates: f.dates, price_display: f.price_display, numbering: f.numbering, global_discount_percent: num(f.global_discount_percent), deposit_percent: num(f.deposit_percent), valid_until: f.valid_until, notes: f.notes };
    try { const { data } = await api.put(`/quotes/${quote.id}/structure`, body); data.warnings.forEach((w) => toast.warning(w)); toast.success("Devis enregistré"); onSaved(); onOpenChange(false); } catch (err) { ko(err); }
  };
  const drag = (id) => ({ draggable: true, onDragStart: (e) => { e.stopPropagation(); e.dataTransfer.setData("text/plain", id); } });
  const drop = (id) => ({ onDragOver: (e) => e.preventDefault(), onDrop: (e) => { e.preventDefault(); e.stopPropagation(); moveTo(e.dataTransfer.getData("text/plain"), id); } });
  const Arrows = ({ id }) => <><button type="button" className="icon-btn" onClick={() => move(id, -1)} aria-label="Monter" data-testid={`block-up-${id}`}><ArrowUp className="h-3.5 w-3.5" /></button><button type="button" className="icon-btn" onClick={() => move(id, 1)} aria-label="Descendre" data-testid={`block-down-${id}`}><ArrowDown className="h-3.5 w-3.5" /></button></>;
  const MoveTo = ({ b }) => <select className={sel} value="" onChange={(e) => moveTo(b.id, e.target.value)} aria-label="Déplacer vers" data-testid={`block-moveto-${b.id}`}><option value="">Déplacer vers…</option>{targets.filter((t) => t.id !== b.parent_id && t.id !== b.id && (b.type !== "subsection" || t.type === "section")).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</select>;
  const Space = ({ b }) => <select className={sel} value={b.space_id} onChange={(e) => (e.target.value === "+" ? newSpace(b.id) : upd(b.id, { space_id: e.target.value }))} aria-label="Emplacement" data-testid={`block-space-${b.id}`}><option value="">{b.type === "line" ? "Emplacement hérité" : "Sans emplacement"}</option>{f.spaces.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}{f.venue_id && <option value="+">+ Nouvel espace</option>}</select>;
  const line = (b) => b.type === "line" ? (
    <div key={b.id} {...drag(b.id)} className="grid grid-cols-12 items-center gap-1.5 rounded-xl border border-border bg-card p-2" data-testid={`block-line-${b.id}`}>
      <GripVertical className="col-span-1 h-4 w-4 cursor-grab text-muted-foreground" />
      <Input required className="col-span-11 h-9 sm:col-span-4" placeholder="Désignation" list="quote-eqs" value={b.label} onChange={(e) => { const m = eqs.find((x) => x.name === e.target.value); upd(b.id, m ? { label: m.name, equipment_id: m.id, kind: "catalog", ...uomOf(m, m.quote_uom === "secondary" ? "secondary" : "") } : { label: e.target.value }); }} data-testid={`line-label-${b.id}`} />
      <Input type="number" min="0.01" step="any" title="Quantité" className="col-span-3 h-9 sm:col-span-1" value={b.qty} onChange={(e) => upd(b.id, { qty: e.target.value })} data-testid={`line-qty-${b.id}`} />
      <Input type="number" step="any" title="Prix unitaire HT" className="col-span-3 h-9 sm:col-span-2" value={b.unit_price} onChange={(e) => upd(b.id, { unit_price: e.target.value, ...(b.source_type ? { price_locked: true } : {}) })} data-testid={`line-price-${b.id}`} />
      <Input type="number" min="0" max="100" step="any" title="TVA %" className="col-span-3 h-9 sm:col-span-1" value={b.vat} onChange={(e) => upd(b.id, { vat: e.target.value })} />
      <Input type="number" min="0" max="100" step="any" title="Remise %" placeholder="Rem. %" className="col-span-3 h-9 sm:col-span-1" value={b.discount_percent || ""} onChange={(e) => upd(b.id, { discount_percent: e.target.value })} />
      <div className="col-span-12 flex flex-wrap items-center gap-1 sm:col-span-2"><Arrows id={b.id} /><button type="button" className="icon-btn" onClick={() => del(b.id)} aria-label="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button></div>
      <div className="col-span-12 flex flex-wrap gap-1.5"><Space b={b} /><MoveTo b={b} />{(() => { const m = eqs.find((x) => x.id === b.equipment_id); return m?.secondary_uom && m.qty_per_piece ? <><select className={sel} value={b.uom || ""} onChange={(e) => upd(b.id, uomOf(m, e.target.value))} aria-label="Unité" data-testid={`line-uom-${b.id}`}><option value="">Quantité en {uomLabel(m.stock_uom, 2)}</option><option value="secondary">Quantité en {m.secondary_uom}</option></select>{b.uom === "secondary" && <span className="self-center text-xs text-muted-foreground" data-testid={`line-conv-${b.id}`}>{b.qty} {m.secondary_uom} → {dual(m, toPieces(m, b.qty))} réservés</span>}</> : null; })()}</div>
      {b.pack_components && <PackLine b={b} upd={upd} />}
      <ReuseLine b={b} B={B} upd={upd} />
      {b.source_type && <div className="col-span-12 flex items-center gap-2 text-xs text-muted-foreground" data-testid={`line-trip-${b.id}`}>Ligne générée par le panneau Logistique & équipe{b.price_locked && <><span className="rounded-full bg-amber-500/20 px-2 py-0.5 font-semibold text-amber-700" data-testid={`line-locked-${b.id}`}>prix manuel</span><button type="button" className="underline" onClick={() => { const x = gen?.find((y) => y.source_id === b.source_id); upd(b.id, { price_locked: false, ...(x ? { unit_price: x.unit_price } : {}) }); }} data-testid={`line-recalc-${b.id}`}>Recalculer</button></>}</div>}
      {f.can_cost && b.unit_cost > 0 && Margin({ b })}
    </div>
  ) : b.type === "text" ? (
    <div key={b.id} className="flex items-start gap-1.5" data-testid={`block-text-${b.id}`}><Textarea rows={2} placeholder="Texte descriptif" value={b.description} onChange={(e) => upd(b.id, { description: e.target.value })} /><Arrows id={b.id} /><button type="button" className="icon-btn" onClick={() => del(b.id)} aria-label="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button></div>
  ) : b.type === "page_break" ? <div key={b.id} className="flex items-center gap-2 text-xs text-muted-foreground">— saut de page —<button type="button" onClick={() => del(b.id)} aria-label="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button></div> : group(b);
  const group = (b) => (
    <div key={b.id} {...(b.type === "subsection" ? drag(b.id) : {})} {...drop(b.id)} onFocusCapture={() => setActive(b.id)} className={`rounded-2xl border p-3 ${b.id === activeId ? "ring-1 ring-primary/40 " : ""}${b.type === "section" ? "border-foreground/30" : "border-dashed border-border bg-secondary/30"}`} data-testid={`block-${b.type}-${b.id}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Input required className="h-9 min-w-40 flex-1 font-semibold" value={b.title} onChange={(e) => upd(b.id, { title: e.target.value })} data-testid={`block-title-${b.id}`} />
        <Space b={b} />
        <select className={sel} value={b.price_display_override} onChange={(e) => upd(b.id, { price_display_override: e.target.value })} aria-label="Affichage des prix de la section"><option value="">Prix : comme le devis</option>{MODES.slice(0, 3).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={b.optional} onChange={(e) => upd(b.id, { optional: e.target.checked })} data-testid={`block-optional-${b.id}`} />Optionnelle</label>
        <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={b.show_subtotal} onChange={(e) => upd(b.id, { show_subtotal: e.target.checked })} />Sous-total</label>
        <Input type="number" min="0" max="100" step="any" title="Remise de section %" placeholder="Rem. %" className="h-9 w-20" value={b.discount_percent || ""} onChange={(e) => upd(b.id, { discount_percent: e.target.value })} />
        <Arrows id={b.id} />{b.type === "subsection" && <MoveTo b={b} />}
        <button type="button" className="icon-btn" onClick={() => setB([...B, ...clone(b.id)])} aria-label="Dupliquer" data-testid={`block-dup-${b.id}`}><Copy className="h-3.5 w-3.5" /></button>
        <button type="button" className="icon-btn" onClick={() => { const name = window.prompt("Nom du modèle de section", b.title); if (name) api.post("/quote-section-templates", { name, blocks: clone(b.id, false) }).then((r) => { setF((x) => ({ ...x, templates: [...x.templates, r.data] })); toast.success("Modèle enregistré"); }).catch(ko); }} aria-label="Enregistrer comme modèle" data-testid={`block-template-${b.id}`}><FileText className="h-3.5 w-3.5" /></button>
        <button type="button" className="icon-btn" onClick={() => window.confirm("Supprimer la section et son contenu ?") && del(b.id)} aria-label="Supprimer la section"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>
      <div className="mt-2 space-y-2">{kids(b.id).map(line)}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {quick(b.id, `quick-add-${b.id}`)}
        <UsageHours b={b} upd={upd} />
        <Button type="button" size="sm" variant="outline" onClick={() => setB([...B, blank("line", b.id)])} data-testid={`add-line-${b.id}`}><Plus />Ligne</Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setB([...B, blank("text", b.id)])}>Texte</Button>
        {b.type === "section" && <Button type="button" size="sm" variant="ghost" onClick={() => setB([...B, blank("subsection", b.id)])} data-testid={`add-subsection-${b.id}`}>Sous-section</Button>}
        <Button type="button" size="sm" variant="ghost" onClick={() => setB([...B, blank("page_break", b.id)])}>Saut de page</Button>
        {f.can_cost && tree(b.id).some((i) => costed.some((x) => x.id === i)) && <Button type="button" size="sm" variant="ghost" onClick={() => bulk(tree(b.id))} data-testid={`block-margin-${b.id}`}>Marge de la section</Button>}
        <span className="ml-auto text-sm font-semibold" data-testid={`block-subtotal-${b.id}`}>{fmtEur2(sub(b.id))} HT{b.optional && !b.selected ? " (option, non comptée)" : ""}</span>
      </div>
    </div>
  );
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[94vh] max-w-5xl overflow-y-auto">
        <DialogHeader><DialogTitle className="flex items-center gap-3 text-xl font-bold">Devis {quote.number}<DuplicateButton q={{ ...quote, event_id: f.event_id }} onDone={onSaved} variant="ghost" label="⋯ Dupliquer" /></DialogTitle></DialogHeader>
        {f.client_modified && <p className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm font-semibold" data-testid="quote-client-modified">Modifié par le client (option cochée ou décochée) : enregistrez pour valider.</p>}
        <form onSubmit={save} className="space-y-4" data-testid="quote-form" onDragOver={(e) => e.dataTransfer.types.includes("Files") && e.preventDefault()} onDrop={(e) => { const file = e.dataTransfer.files?.[0]; if (file && f.can_cost) { e.preventDefault(); setImp({ file }); } }}>
          {activeId && <div className="sticky -top-6 z-30 -mx-1 flex flex-wrap items-center gap-2 border-b border-border bg-background px-1 py-2" data-testid="quote-quick-bar">
            {quick(activeId, "quick-add-top", top)}
            <label className="flex items-center gap-1 text-xs text-muted-foreground">dans<select className={sel} value={activeId} onChange={(e) => setActive(e.target.value)} aria-label="Section de destination" data-testid="quick-add-top-target">{targets.map((t) => <option key={t.id} value={t.id}>{t.type === "subsection" ? "— " : ""}{t.title}</option>)}</select></label>
            <span className="hidden text-xs text-muted-foreground md:inline"><kbd className="rounded border border-border px-1">/</kbd> ou <kbd className="rounded border border-border px-1">Ctrl K</kbd></span>
          </div>}
          <datalist id="quote-eqs">{eqs.map((x) => <option key={x.id} value={x.name} />)}</datalist>
          <Field label="Événement (rattacher ou changer ; vide = détacher)"><Input list="quote-events" value={evText} onChange={(e) => setEvText(e.target.value)} onBlur={(e) => relink(e.target.value.trim())} placeholder="Code ou titre de l'événement" data-testid="quote-event-input" /><datalist id="quote-events">{evs.map((x) => <option key={x.id} value={`${x.code} · ${x.title}`} />)}</datalist></Field>
          {f.dates && <Dates d={f.dates} set={(dates) => setF({ ...f, dates })} />}
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-2">Affichage des prix<select className={sel} value={f.price_display} onChange={(e) => setF({ ...f, price_display: e.target.value })} data-testid="quote-price-display">{MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={f.numbering} onChange={(e) => setF({ ...f, numbering: e.target.checked })} data-testid="quote-numbering" />Numérotation (1, 1.1…)</label>
            <Button type="button" size="sm" variant="outline" onClick={() => downloadPdf(`/quotes/${quote.id}/installation/pdf`, `installation-${quote.number}.pdf`).catch(ko)} data-testid="quote-installation-pdf"><FileText />Fiche d'installation</Button>
            {f.can_cost && <Button type="button" size="sm" variant="outline" onClick={() => window.confirm("Les modifications non enregistrées du devis seront perdues à la validation de l'import. Continuer ?") && setImp({})} data-testid="quote-import-supplier"><Plus />Importer un devis prestataire</Button>}
            {f.can_cost && costed.length > 0 && <Button type="button" size="sm" variant="ghost" onClick={() => bulk(costed.map((b) => b.id))} data-testid="quote-margin-all">Marge sur tout</Button>}
            <Button type="button" size="sm" variant="outline" onClick={() => setLogi(true)} data-testid="quote-logistics-open">Logistique & équipe</Button>
            <span className="text-xs text-muted-foreground">Durée d'exploitation : {f.operation_days} jour(s)</span>
          </div>
          {f.price_display === "none" && <p className="text-sm font-semibold text-red-600" data-testid="quote-none-warning">« Sans prix » : document technique non contractuel ; l'envoi au client et la signature sont bloqués.</p>}
          {tripDiff.length > 0 && <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="trips-banner"><div className="font-semibold">Logistique à recalculer (lieu, dates ou quantités modifiés)</div>{tripDiff.map((x) => <div key={x} className="text-xs">{x}</div>)}<div className="mt-2 flex gap-2"><Button type="button" size="sm" onClick={() => { setB(mergeTrips(B, gen)); setGen(null); }} data-testid="trips-banner-apply">Appliquer</Button><Button type="button" size="sm" variant="ghost" onClick={() => setGen(null)} data-testid="trips-banner-ignore">Ignorer</Button></div></div>}
          <DjQuoteBox quoteId={quote.id} />
          <TranslationAlert quoteId={quote.id} />
          <TitleTranslations base={`/quotes/${quote.id}`} label="Titre du devis par langue" />
          <ReuseBanner B={B} setB={setB} />
          <div className="space-y-3">{kids("").map(group)}</div>
          <div className="flex flex-wrap gap-2"><Button type="button" size="sm" onClick={() => setB([...B, blank("section", "")])} data-testid="quote-add-section"><Plus />Section</Button>
            {f.templates.length > 0 && <select className={sel} value="" onChange={(e) => { const t = f.templates.find((x) => x.id === e.target.value); if (!t) return; const map = Object.fromEntries(t.blocks.map((b) => [b.id, uid()])); setB([...B, ...t.blocks.map((b) => ({ ...b, id: map[b.id], parent_id: map[b.parent_id] || "" }))]); }} data-testid="quote-insert-template"><option value="">Insérer un modèle de section…</option>{f.templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>}</div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Field label="Remise globale (%)"><Input type="number" min="0" max="100" step="any" value={f.global_discount_percent} onChange={(e) => setF({ ...f, global_discount_percent: e.target.value })} data-testid="quote-global-discount" /></Field>
            <Field label="Acompte (%)"><Input type="number" min="0" max="99" step="any" value={f.deposit_percent} onChange={(e) => setF({ ...f, deposit_percent: e.target.value })} data-testid="quote-deposit-input" /></Field>
            <Field label="Valable jusqu'au"><Input type="date" value={f.valid_until} onChange={(e) => setF({ ...f, valid_until: e.target.value })} data-testid="quote-valid-input" /></Field>
            <Field label="Notes (PDF)" className="col-span-2 md:col-span-4"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
          </div>
          <div className="ml-auto w-full max-w-xs text-sm" data-testid="quote-totals">
            <div className="flex justify-between py-1 text-muted-foreground"><span>Total HT</span><span>{fmtEur2(ht)}</span></div><div className="flex justify-between py-1 text-muted-foreground"><span>TVA</span><span>{fmtEur2(vat)}</span></div>
            <div className="flex justify-between border-t border-border py-2 font-bold"><span>Total TTC</span><span data-testid="quote-total-ttc">{fmtEur2(ht + vat)}</span></div>
            {f.can_cost && costTotal > 0 && <div className="mb-1 rounded-lg bg-secondary/50 p-2 text-xs" data-testid="quote-margin-by-kind">{byKind.map(([l, fn]) => { const rows = counted.filter(fn); const v = rows.reduce((n, b) => n + b.qty * price(b)[0], 0); const c = rows.reduce((n, b) => n + b.qty * (b.unit_cost || 0), 0); return rows.length ? <div key={l} className="flex justify-between"><span>{l}</span><span>vente {fmtEur2(v)} · coût {fmtEur2(c)} · marge {fmtEur2(v - c)}</span></div> : null; })}</div>}
            {f.can_cost && costTotal > 0 && <div className="rounded-lg bg-secondary/50 p-2 text-xs" data-testid="quote-margin-totals">Interne — coût prestataires {fmtEur2(costTotal)} · marge {fmtEur2(costedHt - costTotal)} ({costedHt ? Math.round(((costedHt - costTotal) / costedHt) * 1000) / 10 : 0} %)</div>}
          </div>
          {f.can_cost && <SupplierQuotes rows={f.supplier_quotes} />}
          <QuoteMaterial quoteId={quote.id} canEdit />
          <DialogFooter><Button data-testid="quote-form-submit">Enregistrer</Button></DialogFooter>
        </form>
        {logi && <LogisticsPanel quoteId={quote.id} blocks={B} dates={f.dates} onClose={() => setLogi(false)} onApply={(data) => { setF((x) => ({ ...x, has_trips: true, blocks: mergeTrips(x.blocks, data.lines) })); setGen(null); setLogi(false); }} />}
        {np && <NewProduct value={np} eqs={eqs} onClose={() => setNp(null)} onCreated={(eq) => { setEqs((x) => [...x, eq]); addCatalog(np.pid, { ...eq, price: np.price ?? eq.price_day }, np.qty); setNp(null); }} />}
        {imp && <SupplierImport quoteId={quote.id} file={imp.file} sections={targets} spaces={f.spaces} onClose={() => setImp(null)} onDone={reload} />}
      </DialogContent>
    </Dialog>
  );
}
