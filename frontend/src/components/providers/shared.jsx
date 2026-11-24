import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { fmtEur2 } from "@/lib/constants";

export const EQUIP = { sono: "Sono / table de mixage", micro: "Micro", retour: "Retour", prise_220v: "Prise 220 V", pupitre: "Pupitre", eclairage: "Éclairage", loge: "Loge", repas: "Repas", parking: "Parking" };
export const TRAVEL = { included: "Inclus", flat: "Forfait fixe", per_km: "€/km depuis la ville de base", quote: "Sur devis" };
export const LEGAL = { micro: "Auto-entrepreneur", company: "Société", guso: "Intermittent (GUSO / cachet)" };
export const P_STATUS = { active: "Actif", test: "En test", blocked: "Ne plus solliciter" };
export const R_STATUS = { draft: "Brouillon", sent: "Envoyée", in_progress: "En cours", filled: "Pourvue", cancelled: "Annulée" };
export const REPLY = { queued: "En attente d'envoi", sent: "Envoyé", opened: "Ouvert", available: "Disponible", unavailable: "Pas dispo", conditional: "Sous conditions", retained: "Retenu", error: "Échec d'envoi" };
export const M_STATUS = { confirmed: "Confirmée", done: "Réalisée", invoiced: "Facturée", paid: "Payée" };
export const NOT_SUBJECT = "TVA non applicable, art. 293 B du CGI";

export const priceLabel = (vatMode, ht, ttc) => (vatMode === "subject" ? `${fmtEur2(ht)} HT · ${fmtEur2(ttc)} TTC` : `${fmtEur2(ht)} net — TVA non applicable`);
export const travelLabel = (p) => (p.travel_fee_mode === "flat" ? `Forfait ${fmtEur2(p.travel_fee_amount)}` : p.travel_fee_mode === "per_km"
  ? `${String(p.travel_fee_amount).replace(".", ",")} €/km${p.travel_km_included ? ` (${p.travel_km_included} km inclus)` : ""}` : TRAVEL[p.travel_fee_mode]);
export const equipText = (keys, labels = EQUIP) => keys.map((k) => labels[k] || k).join(", ");

export const Badge = ({ tone = "muted", children, testid }) => (
  <span data-testid={testid} className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${{ muted: "bg-secondary text-secondary-foreground", ok: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400", warn: "bg-amber-500/15 text-amber-700 dark:text-amber-400", bad: "bg-red-500/15 text-red-700 dark:text-red-400", info: "bg-primary/10 text-primary" }[tone]}`}>{children}</span>
);

export const Chips = ({ options, value, onChange, testid }) => (
  <div className="flex flex-wrap gap-1.5" data-testid={testid}>
    {options.map(([k, l]) => {
      const on = value.includes(k);
      return <button key={k} type="button" aria-pressed={on} data-testid={`${testid}-${k}`} onClick={() => onChange(on ? value.filter((x) => x !== k) : [...value, k])}
        className={`h-8 rounded-full border px-3 text-xs font-medium transition-colors ${on ? "border-primary bg-primary text-white" : "border-border hover:bg-secondary"}`}>{l}</button>;
    })}
  </div>
);

export const ListInput = ({ value, onChange, ...p }) => {
  const [t, setT] = useState(value.join(", "));
  useEffect(() => { setT((cur) => (cur.split(",").map((x) => x.trim()).filter(Boolean).join("|") === value.join("|") ? cur : value.join(", "))); }, [value]);
  return <Input value={t} onChange={(e) => { setT(e.target.value); onChange(e.target.value.split(",").map((x) => x.trim()).filter(Boolean)); }} {...p} />;
};

export function GeoInput({ value, onText, onPick, municipality, testid, ...p }) {
  const [q, setQ] = useState("");
  const [opts, setOpts] = useState([]);
  useEffect(() => {
    if (q.trim().length < 3) { setOpts([]); return undefined; }
    const t = setTimeout(() => fetch(`https://data.geopf.fr/geocodage/search?limit=5${municipality ? "&type=municipality" : ""}&q=${encodeURIComponent(q)}`).then((r) => r.json())
      .then((d) => setOpts(d.features || [])).catch(() => setOpts([])), 250);
    return () => clearTimeout(t);
  }, [q, municipality]);
  return (
    <div className="relative">
      <Input value={value} autoComplete="off" data-testid={testid} onChange={(e) => { onText(e.target.value); setQ(e.target.value); }} onBlur={() => setTimeout(() => setOpts([]), 150)} {...p} />
      {opts.length > 0 && (
        <ul className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-md" data-testid={`${testid}-options`}>
          {opts.map((o, i) => (
            <li key={i} data-testid={`${testid}-option-${i}`} className="cursor-pointer rounded-lg px-3 py-2 text-sm hover:bg-secondary"
              onMouseDown={(e) => { e.preventDefault(); setOpts([]); setQ(""); onPick(o.properties, o.geometry?.coordinates); }}>
              <div className="font-medium">{o.properties.name}</div><div className="text-xs text-muted-foreground">{o.properties.postcode} {o.properties.city}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
