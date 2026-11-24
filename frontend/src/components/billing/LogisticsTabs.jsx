import { Plus, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { fmtEur2 } from "@/lib/constants";

const sel = "h-9 rounded-lg border border-border bg-background px-2 text-xs";
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
const n = (v) => Number(String(v ?? "").replace(",", ".")) || 0;
const PH = { delivery: "Livraison / installation", operation: "Exploitation", pickup: "Retrait / démontage", custom: "Créneau libre" };
const UNITS = { hour: "À l'heure", shift: "Vacation", day: "Jour", flat: "Forfait" };
const SRC = { average: "À affecter plus tard (coût moyen du rôle)", employee: "Salarié", provider: "Prestataire" };
const TYPES = { lodging: "Hébergement", meal: "Repas", toll: "Péages", parking: "Parking", train: "Train", plane: "Avion", other: "Autre" };
const MODES = { flat: "Refacturé au forfait", actual: "Au réel sur justificatifs", included: "Inclus (non montré au client)", client_provided: "Pris en charge par le client" };
const hm = (m) => `${Math.floor(m / 60)} h ${String(Math.round(m % 60)).padStart(2, "0")}`;

export const slimLabor = (x) => ({ id: x.id, role: x.role, headcount: Math.max(1, Math.round(n(x.headcount))), phase: x.phase, date: x.date || "", start: x.start || "", end: x.end || "", hours: n(x.hours), unit: x.unit, cost_source: x.cost_source || "average", contract: x.contract || "cddu", gross_hour: n(x.gross_hour), provider_rate: n(x.provider_rate), unit_price_ht: n(x.unit_price_ht), trip_id: x.trip_id || "" });
export const slimExpense = (x) => ({ id: x.id, type: x.type, label: x.label || "", persons: Math.max(1, Math.round(n(x.persons))), qty: n(x.qty), unit_cost_ht: n(x.unit_cost_ht), unit_price_ht: n(x.unit_price_ht), mode: x.mode, vat_rate: n(x.vat_rate), debours: !!x.debours, note: x.note || "" });
const newLabor = (p) => ({ id: uid(), role: "technicien_son", headcount: 1, phase: "operation", date: "", start: "", end: "", hours: 0, unit: "shift", cost_source: "average", contract: "cddu", gross_hour: 0, provider_rate: 0, unit_price_ht: 0, trip_id: "", ...p });

export function TripTeam({ d, t, i, push }) {
  const team = d.labor.filter((x) => x.trip_id === t.id);
  const add = (role) => push({ ...d, labor: [...d.labor, newLabor({ role, unit: "hour", trip_id: t.id, hours: Math.ceil((t.duration_minutes || 240) / 30) / 2, ...(t.type === "extra" ? { phase: "custom", date: t.date, start: t.slot_start || "08:00" } : { phase: t.type }) })] }, true);
  return (
    <div className="mt-3 text-xs" data-testid={`trip-team-${i}`}>
      <span className="text-muted-foreground">Durée estimée : {hm(t.duration_minutes || 0)} (route aller-retour + {hm(t.handling_minutes || 0)} de chargement / déchargement)</span>
      <div className="mt-1 flex flex-wrap items-center gap-2"><b>Équipe du trajet :</b>{team.map((x) => <span key={x.id} className="rounded-full bg-secondary px-2 py-0.5">{x.headcount} × {d.roles[x.role] || x.role} · {x.computed_hours ?? x.hours} h</span>)}{!team.length && <span className="text-muted-foreground">personne</span>}
        <button type="button" className="underline" onClick={() => add("chauffeur")} data-testid={`trip-add-driver-${i}`}>+ Chauffeur</button><button type="button" className="underline" onClick={() => add("manutentionnaire")} data-testid={`trip-add-handler-${i}`}>+ Manutentionnaire</button></div>
    </div>);
}

export function LaborTab({ d, push, pill }) {
  const up = (id, patch, now) => push({ ...d, labor: d.labor.map((x) => (x.id === id ? { ...x, ...patch } : x)) }, now);
  const num = (x, k, label, tid, w = "w-20") => <label className="flex items-center gap-1 text-xs text-muted-foreground">{label}<Input className={`h-9 ${w}`} type="number" min="0" step="any" value={x[k]} onChange={(e) => up(x.id, { [k]: e.target.value })} data-testid={tid} /></label>;
  return (
    <div className="mt-4 space-y-3" data-testid="labor-tab">
      {d.labor.map((x, i) => (
        <div key={x.id} className="rounded-2xl border border-border p-4" data-testid={`labor-${i}`}>
          <div className="flex flex-wrap items-center gap-2">
            <select className={sel} value={x.role} onChange={(e) => up(x.id, { role: e.target.value }, true)} data-testid={`labor-role-${i}`}>{Object.entries(d.roles).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            {num(x, "headcount", "Personnes", `labor-headcount-${i}`, "w-16")}
            <select className={sel} value={x.phase} onChange={(e) => up(x.id, { phase: e.target.value }, true)} data-testid={`labor-phase-${i}`}>{Object.entries(PH).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <select className={sel} value={x.unit} onChange={(e) => up(x.id, { unit: e.target.value }, true)} data-testid={`labor-unit-${i}`}>{Object.entries(UNITS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <span className="flex-1" />{x.trip_id && <span className="rounded-full bg-secondary px-2 py-0.5 text-xs">équipe d'un trajet</span>}
            <button type="button" aria-label="Supprimer le poste" onClick={() => push({ ...d, labor: d.labor.filter((y) => y.id !== x.id) }, true)} data-testid={`labor-remove-${i}`}><Trash2 className="h-4 w-4" /></button></div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {x.phase === "custom" && <><Input className="h-9 w-40" type="date" value={x.date} onChange={(e) => up(x.id, { date: e.target.value })} data-testid={`labor-date-${i}`} /><Input className="h-9 w-28" type="time" value={x.start} onChange={(e) => up(x.id, { start: e.target.value })} data-testid={`labor-start-${i}`} /><Input className="h-9 w-28" type="time" value={x.end} onChange={(e) => up(x.id, { end: e.target.value })} data-testid={`labor-end-${i}`} /></>}
            {num(x, "hours", "Durée imposée (h, 0 = créneau)", `labor-hours-${i}`)}
            {x.unit === "flat" && num(x, "unit_price_ht", "Prix HT / personne", `labor-price-input-${i}`, "w-24")}</div>
          {d.can_cost && <div className="mt-2 flex flex-wrap items-center gap-2">
            <select className={sel} value={x.cost_source} onChange={(e) => up(x.id, { cost_source: e.target.value }, true)} data-testid={`labor-source-${i}`}>{Object.entries(SRC).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            {x.cost_source === "employee" && <><select className={sel} value={x.contract} onChange={(e) => up(x.id, { contract: e.target.value }, true)} data-testid={`labor-contract-${i}`}>{d.contracts.map((c) => <option key={c} value={c}>{c.toUpperCase()}</option>)}</select>{num(x, "gross_hour", "Brut / h", `labor-gross-${i}`)}</>}
            {x.cost_source === "provider" && num(x, "provider_rate", "Tarif HT / personne (déplacement inclus)", `labor-provider-rate-${i}`, "w-24")}</div>}
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-secondary/50 p-2 text-xs">
            <span data-testid={`labor-slot-${i}`}>{x.start_at ? `${x.start_at.replace("T", " ")} → ${x.end_at.slice(11)} · ${x.computed_hours} h` : "Créneau à préciser (dates du devis manquantes)"}</span>
            {x.surcharge_note && <span className="rounded-full bg-amber-500/20 px-2 py-0.5 font-semibold text-amber-700" data-testid={`labor-surcharge-${i}`}>Majoration : {x.surcharge_note} (× {x.multiplier})</span>}
            <span className="flex-1" /><span>Prix client <b data-testid={`labor-price-${i}`}>{fmtEur2(x.price_ht || 0)}</b></span>{d.can_cost && <span data-testid={`labor-cost-${i}`}>· coût {fmtEur2(x.cost_ht || 0)} · marge {fmtEur2((x.price_ht || 0) - (x.cost_ht || 0))}</span>}</div>
          <p className="mt-1 text-xs text-muted-foreground">Ligne client : {x.client_label}</p>
        </div>))}
      <button type="button" className="text-sm underline" onClick={() => push({ ...d, labor: [...d.labor, newLabor()] }, true)} data-testid="labor-add"><Plus className="mr-1 inline h-4 w-4" />Poste</button>
      <div className="flex flex-wrap items-center gap-2 text-sm"><span className="font-semibold">Affichage client</span>{[["detailed", "Une ligne par poste"], ["grouped", "Regroupé : « Main-d'œuvre »"]].map(([k, l]) => <button key={k} type="button" className={pill(d.labor_display === k)} onClick={() => push({ ...d, labor_display: k }, true)} data-testid={`labor-display-${k}`}>{l}</button>)}</div>
      <p className="text-xs text-muted-foreground">Ni le nom ni le coût des personnes n'apparaissent côté client. À la signature du devis, chaque poste est créé dans le module Staff de l'événement.</p>
    </div>);
}

export function ExpensesTab({ d, push }) {
  const up = (id, patch, now) => push({ ...d, expenses: d.expenses.map((x) => (x.id === id ? { ...x, ...patch } : x)) }, now);
  const num = (x, k, label, tid, w = "w-20") => <label className="flex items-center gap-1 text-xs text-muted-foreground">{label}<Input className={`h-9 ${w}`} type="number" min="0" step="any" value={x[k] ?? 0} onChange={(e) => up(x.id, { [k]: e.target.value })} data-testid={tid} /></label>;
  const fresh = d.suggested_expenses.filter((s) => !d.expenses.some((e) => e.type === s.type && e.label === s.label));
  return (
    <div className="mt-4 space-y-3" data-testid="expenses-tab">
      {fresh.length > 0 && <div className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="expenses-suggestions"><div className="font-semibold">Proposé d'après l'équipe et les trajets</div>
        {fresh.map((s) => <div key={s.id} className="text-xs">{s.label} : {s.persons} personne(s) × {s.qty} — {fmtEur2(s.unit_price_ht)} HT l'unité</div>)}
        <button type="button" className="mt-2 text-xs font-semibold underline" onClick={() => push({ ...d, expenses: [...d.expenses, ...fresh] }, true)} data-testid="expenses-suggestions-add">Ajouter ces frais (refacturés au forfait, TVA 20 %)</button></div>}
      {d.expenses.map((x, i) => (
        <div key={x.id} className="rounded-2xl border border-border p-4" data-testid={`expense-${i}`}>
          <div className="flex flex-wrap items-center gap-2">
            <select className={sel} value={x.type} onChange={(e) => up(x.id, { type: e.target.value }, true)} data-testid={`expense-type-${i}`}>{Object.entries(TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <Input className="h-9 w-40" placeholder="Libellé" value={x.label} onChange={(e) => up(x.id, { label: e.target.value })} data-testid={`expense-label-${i}`} />
            {num(x, "persons", "Personnes", `expense-persons-${i}`, "w-16")}{num(x, "qty", "×", `expense-qty-${i}`, "w-16")}
            <span className="flex-1" /><button type="button" aria-label="Supprimer le frais" onClick={() => push({ ...d, expenses: d.expenses.filter((y) => y.id !== x.id) }, true)} data-testid={`expense-remove-${i}`}><Trash2 className="h-4 w-4" /></button></div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select className={sel} value={x.mode} onChange={(e) => up(x.id, { mode: e.target.value }, true)} data-testid={`expense-mode-${i}`}>{Object.entries(MODES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            {d.can_cost && x.mode !== "client_provided" && num(x, "unit_cost_ht", "Coût HT unitaire", `expense-cost-${i}`)}
            {["flat", "actual"].includes(x.mode) && <>{num(x, "unit_price_ht", "Prix HT unitaire", `expense-price-${i}`)}{!x.debours && num(x, "vat_rate", "TVA %", `expense-vat-${i}`, "w-16")}
              <label className="flex items-center gap-1 text-xs" title="Débours : uniquement pour une dépense engagée au nom et pour le compte du client, facture au nom du client, refacturée à l'euro près, sans marge et sans TVA (compte de passage). Sinon, laissez décoché : les frais refacturés suivent la TVA de la prestation."><input type="checkbox" checked={x.debours} onChange={(e) => up(x.id, { debours: e.target.checked }, true)} data-testid={`expense-debours-${i}`} />Débours</label></>}
            <span className="flex-1" /><span className="text-xs">Client <b data-testid={`expense-total-${i}`}>{fmtEur2(x.price_ht || 0)}</b>{d.can_cost && ` · coût ${fmtEur2(x.cost_ht || 0)}`}</span></div>
          {x.mode === "client_provided" && <p className="mt-1 text-xs text-muted-foreground">Ligne à 0 € « fournis par le client » ; une tâche « Confirmer hébergement fourni » sera créée à la signature, sans engagement de charge.</p>}
          {x.mode === "actual" && <p className="mt-1 text-xs text-muted-foreground">Montant estimatif, mention « refacturé au réel sur justificatifs » sur le devis.</p>}
        </div>))}
      <button type="button" className="text-sm underline" onClick={() => push({ ...d, expenses: [...d.expenses, { id: uid(), type: "other", label: "", persons: 1, qty: 1, unit_cost_ht: 0, unit_price_ht: 0, mode: "flat", vat_rate: 20, debours: false, note: "" }] }, true)} data-testid="expense-add"><Plus className="mr-1 inline h-4 w-4" />Frais</button>
      {d.can_cost && d.included_cost_ht > 0 && <p className="text-xs text-muted-foreground" data-testid="expenses-included">Frais « inclus » absorbés dans la marge : {fmtEur2(d.included_cost_ht)} (non reportés dans le coût des lignes).</p>}
    </div>);
}

export function ClientPreview({ d, blocks }) {
  const rows = [...blocks.filter((b) => b.type === "line" && !b.source_type).map((b) => ({ id: b.id, label: b.label, qty: n(b.qty), unit_price: n(b.unit_price), vat: n(b.vat) })), ...d.lines.map((l) => ({ ...l, id: l.source_id, gen: true }))];
  const ht = rows.reduce((s, r) => s + r.qty * r.unit_price, 0);
  return (
    <div className="mt-4 rounded-2xl border border-border p-4" data-testid="client-preview">
      <p className="mb-3 text-xs text-muted-foreground">Ce que le client verra (hors remises, options et mise en page) : jamais de coût, de marge, de distance ni de nom de personne.</p>
      <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th>Désignation</th><th className="text-right">Qté</th><th className="text-right">PU HT</th><th className="text-right">TVA</th><th className="text-right">Total HT</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id} className={`border-t border-border ${r.gen ? "bg-secondary/40" : ""}`} data-testid={r.gen ? "client-preview-generated" : undefined}><td className="py-1.5 pr-2">{r.label}</td><td className="text-right">{r.qty}</td><td className="text-right">{fmtEur2(r.unit_price)}</td><td className="text-right">{r.vat} %</td><td className="text-right">{fmtEur2(r.qty * r.unit_price)}</td></tr>)}</tbody>
        <tfoot><tr className="border-t border-border font-semibold"><td colSpan={4} className="py-1.5">Total HT estimé</td><td className="text-right" data-testid="client-preview-total">{fmtEur2(ht)}</td></tr></tfoot></table>
    </div>);
}
