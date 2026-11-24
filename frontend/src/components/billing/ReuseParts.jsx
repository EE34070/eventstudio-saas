import { Input } from "@/components/ui/input";

const sel = "h-8 rounded-lg border border-border bg-background px-2 text-xs";
const m = (s) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5));
const hoursOf = (B, b) => { for (let x = b; x; x = B.find((y) => y.id === x.parent_id)) if (x.usage_start && x.usage_end) { let a = m(x.usage_start), e = m(x.usage_end); if (a < 360) a += 1440; while (e <= a) e += 1440; return { a, e, title: x.title, id: x.id }; } return null; };
const sources = (B, b) => B.filter((s) => s.type === "line" && s.id !== b.id && s.equipment_id && s.equipment_id === b.equipment_id && !s.reuse_from && hoursOf(B, s)?.id !== hoursOf(B, b)?.id);

export function UsageHours({ b, upd }) {
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground" title="Interne : jamais montré au client. Sert à proposer le réemploi du matériel entre sections." data-testid={`usage-${b.id}`}>Utilisé de
      <Input className="h-8 w-24" type="time" value={b.usage_start || ""} onChange={(e) => upd(b.id, { usage_start: e.target.value })} data-testid={`usage-start-${b.id}`} />à
      <Input className="h-8 w-24" type="time" value={b.usage_end || ""} onChange={(e) => upd(b.id, { usage_end: e.target.value })} data-testid={`usage-end-${b.id}`} /></span>);
}

export function ReuseLine({ b, B, upd }) {
  const opts = sources(B, b);
  if (!b.equipment_id || (!opts.length && !b.reuse_from)) return null;
  const bad = b.reuse_status === "invalid";
  return (
    <div className="col-span-12 flex flex-wrap items-center gap-2 text-xs text-muted-foreground" data-testid={`reuse-${b.id}`}>Réemployer depuis (interne)
      <select className={sel} value={b.reuse_from || ""} onChange={(e) => upd(b.id, { reuse_from: e.target.value, reuse_qty: 0, reuse_status: "", reuse_alert: "" })} data-testid={`reuse-from-${b.id}`}><option value="">— aucun —</option>{opts.map((s) => <option key={s.id} value={s.id}>{hoursOf(B, s)?.title || "section"} · {s.qty} × {s.label}</option>)}</select>
      {b.reuse_from && <><label className="flex items-center gap-1">quantité<Input className="h-8 w-16" type="number" min="0" step="any" value={b.reuse_qty || ""} placeholder="tout" onChange={(e) => upd(b.id, { reuse_qty: Number(e.target.value) || 0 })} data-testid={`reuse-qty-${b.id}`} /></label>
        {b.reuse_status && <span className={`rounded-full px-2 py-0.5 font-semibold ${bad ? "bg-red-500/15 text-red-700" : "bg-emerald-500/15 text-emerald-700"}`} data-testid={`reuse-status-${b.id}`}>{bad ? "invalide" : b.reuse_status === "forced" ? `forcé : −${b.reuse_effective}` : `validé : −${b.reuse_effective} mobilisé`}</span>}
        {b.reuse_alert && <span className={bad ? "font-semibold text-red-600" : "font-semibold text-amber-600"} data-testid={`reuse-alert-${b.id}`}>{b.reuse_alert}</span>}
        {bad && <Input className="h-8 w-56" placeholder="Forcer : motif obligatoire" value={b.reuse_force_reason || ""} onChange={(e) => upd(b.id, { reuse_force_reason: e.target.value })} data-testid={`reuse-force-${b.id}`} />}</>}
    </div>);
}

export function ReuseBanner({ B, setB }) {
  const sug = B.filter((b) => b.type === "line" && b.equipment_id && !b.reuse_from && !b.reuse_ignored).flatMap((b) => { const h = hoursOf(B, b); const s = h && sources(B, b).find((x) => { const g = hoursOf(B, x); return g && g.e <= h.a; }); return s ? [{ b, s, n: Math.min(b.qty, s.qty), from: hoursOf(B, s).title, to: h.title }] : []; });
  if (!sug.length) return null;
  const set = (ids, patch) => setB(B.map((x) => (ids[x.id] ? { ...x, ...patch(ids[x.id]) } : x)));
  const all = Object.fromEntries(sug.map((x) => [x.b.id, x]));
  return (
    <div className="rounded-xl border border-emerald-500/50 bg-emerald-500/10 p-3 text-sm" data-testid="reuse-banner"><div className="font-semibold">Réemploi possible (interne, invisible du client)</div>
      {sug.map((x) => <div key={x.b.id} className="text-xs">−{x.n} {x.b.label} : {x.from} → {x.to}</div>)}
      <div className="mt-2 flex gap-3 text-xs"><button type="button" className="font-semibold underline" onClick={() => set(all, (x) => ({ reuse_from: x.s.id, reuse_qty: x.n }))} data-testid="reuse-banner-apply">Valider ces réemplois</button><button type="button" className="underline" onClick={() => set(all, () => ({ reuse_ignored: true }))} data-testid="reuse-banner-ignore">Ignorer</button></div>
      <p className="mt-1 text-xs text-muted-foreground">Enregistrez le devis pour que le stock mobilisé soit recalculé.</p></div>);
}
