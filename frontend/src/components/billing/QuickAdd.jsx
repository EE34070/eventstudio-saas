import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { fmtEur2 } from "@/lib/constants";

export const parseQty = (raw) => {
  const t = raw.trim();
  const m = t.match(/^(\d+(?:[.,]\d+)?)\s*x?\s+(.+)$/i) || t.match(/^(.+?)\s*x\s*(\d+(?:[.,]\d+)?)$/i);
  if (!m) return { text: t, qty: 1 };
  const first = /^\d/.test(m[1]);
  return { text: (first ? m[2] : m[1]).trim(), qty: Number((first ? m[1] : m[2]).replace(",", ".")) || 1 };
};

export function QuickAdd({ onAdd, onFree, onCreate, canCreate, testid, eventId, inputRef }) {
  const [text, setText] = useState("");
  const [items, setItems] = useState([]);
  const [free, setFree] = useState([]);
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const [busy, setBusy] = useState(false);
  const box = useRef(null);
  const { text: q, qty } = parseQty(text);
  useEffect(() => {
    if (q.length < 2) { setItems([]); setFree([]); setBusy(false); return undefined; }
    const ctl = new AbortController();
    setBusy(true);
    const t = setTimeout(() => api.get("/catalog/search", { params: { q, event_id: eventId || undefined }, signal: ctl.signal })
      .then((r) => { setItems(r.data.items); setFree(r.data.free || []); setSel(0); setBusy(false); }).catch(() => {}), 150);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q, eventId]);
  useEffect(() => {
    const out = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", out);
    return () => document.removeEventListener("mousedown", out);
  }, []);
  const done = () => { setText(""); setItems([]); setFree([]); setOpen(false); };
  const add = (it) => { onAdd(it, qty); done(); };
  const libre = (label = q, price) => { if (label.length < 2) return; onFree(label, qty, price); done(); };
  const create = (name = q, price) => { if (!canCreate || name.length < 2) return; onCreate(name, qty, price); done(); };
  const key = (e) => {
    if (e.key === "Escape") { if (open) e.stopPropagation(); setOpen(false); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setOpen(true); setSel((s) => Math.max(0, Math.min(items.length - 1, s + (e.key === "ArrowDown" ? 1 : -1)))); }
    if (e.key === "Enter") { e.preventDefault(); if (e.ctrlKey || e.metaKey) (e.shiftKey ? create() : libre()); else if (open && items[sel]) add(items[sel]); }
  };
  const act = "flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium hover:bg-secondary";
  return (
    <div ref={box} className="relative min-w-64 flex-1" data-testid={testid}>
      <input ref={inputRef} className="h-9 w-full rounded-lg border border-border bg-background px-3 text-sm" placeholder="+ Ajouter un article… (ex. 4 enceinte)" value={text} autoComplete="off"
        onChange={(e) => { setText(e.target.value); setOpen(true); }} onFocus={() => text && setOpen(true)} onKeyDown={key} data-testid={`${testid}-input`} />
      {open && q.length >= 2 && (
        <div className="absolute left-0 right-0 z-40 mt-1 max-h-96 overflow-y-auto rounded-xl border border-border bg-card shadow-lg" data-testid={`${testid}-list`} data-query={busy ? "" : q}>
          {!items.length && <p className="p-3 text-xs text-muted-foreground" data-testid={`${testid}-empty`}>{busy ? "Recherche…" : `Aucun article du catalogue pour « ${q} ».`}</p>}
          {items.map((it, i) => (
            <button key={it.id} type="button" onMouseEnter={() => setSel(i)} onClick={() => add(it)} className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm ${i === sel ? "bg-secondary" : ""}`} data-testid={`${testid}-item-${i}`} aria-selected={i === sel}>
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{it.name}</span><span className="block truncate text-xs text-muted-foreground">{[it.ref, it.category].filter(Boolean).join(" · ")}</span></span>
              <span className="shrink-0 text-xs text-muted-foreground" data-testid={`${testid}-avail-${i}`}><span className={`mr-1 inline-block h-2 w-2 rounded-full ${it.available > 0 ? "bg-emerald-500" : "bg-red-500"}`} />dispo {it.available}{it.at_event_dates ? " aux dates" : ""}</span>
              {it.price != null && <span className="shrink-0 text-xs font-medium">{fmtEur2(it.price)}</span>}
            </button>))}
          {!!free.length && <div className="border-t border-border" data-testid={`${testid}-free-section`}>
            <p className="px-3 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Prestations libres déjà utilisées</p>
            {free.map((x, i) => (
              <div key={x.label} className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-secondary">
                <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => libre(x.label, x.price)} data-testid={`${testid}-free-${i}`}>{x.label}<span className="ml-2 text-xs text-muted-foreground">{x.uses} fois{x.price != null ? ` · ${fmtEur2(x.price)}` : ""}</span></button>
                {canCreate && x.uses >= 3 && <button type="button" className="shrink-0 text-xs underline" onClick={() => create(x.label, x.price)} data-testid={`${testid}-free-create-${i}`}>Créer au catalogue</button>}
              </div>))}
          </div>}
          {qty !== 1 && <p className="border-t border-border px-3 py-1 text-xs text-muted-foreground">Quantité : {qty}</p>}
          <div className="sticky bottom-0 border-t border-border bg-card">
            {canCreate && <button type="button" className={act} onClick={() => create()} data-testid={`${testid}-create-product`}><span className="truncate">+ Créer le produit « {q} »</span><kbd className="shrink-0 text-[11px] text-muted-foreground">Ctrl Maj Entrée</kbd></button>}
            <button type="button" className={act} onClick={() => libre()} data-testid={`${testid}-free-line`}><span className="truncate">+ Prestation libre « {q} »</span><kbd className="shrink-0 text-[11px] text-muted-foreground">Ctrl Entrée</kbd></button>
          </div>
        </div>)}
    </div>);
}
