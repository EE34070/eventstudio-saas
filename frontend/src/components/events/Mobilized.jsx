import { useEffect, useState } from "react";
import { Section } from "@/components/common";
import { api } from "@/lib/api";

export function Mobilized({ eid }) {
  const [d, setD] = useState(null);
  useEffect(() => { api.get(`/events/${eid}/mobilized`).then((r) => setD(r.data)).catch(() => {}); }, [eid]);
  if (!d?.rows.length) return null;
  const sum = (k) => d.rows.reduce((n, r) => n + r[k], 0);
  return (
    <Section title="Stock mobilisé" testid="mobilized-section" actions={<span className="text-xs text-muted-foreground">{d.basis === "accepte" ? "D'après les devis acceptés" : "D'après les devis en cours (non acceptés)"} · interne</span>}>
      <table className="w-full text-sm"><thead><tr className="border-b border-border text-left text-xs text-muted-foreground"><th className="py-2">Article</th><th className="text-right">Devisé</th><th className="text-right">Réemployé</th><th className="text-right">Mobilisé</th></tr></thead>
        <tbody>{d.rows.map((r) => <tr key={r.equipment_id} className="border-b border-border" data-testid={`mobilized-row-${r.equipment_id}`}><td className="py-1.5">{r.label}</td><td className="text-right">{r.quoted}</td><td className={`text-right ${r.reused ? "font-semibold text-amber-600" : "text-muted-foreground"}`}>{r.reused || "—"}</td><td className="text-right font-semibold">{r.mobilized}</td></tr>)}
          <tr className="font-semibold" data-testid="mobilized-total"><td className="py-1.5">Total</td><td className="text-right">{sum("quoted")}</td><td className="text-right">{sum("reused")}</td><td className="text-right">{sum("mobilized")}</td></tr></tbody></table>
      {d.transfers.length > 0 && <div className="mt-3 rounded-xl border border-amber-500/50 bg-amber-500/10 p-3 text-sm" data-testid="mobilized-transfers"><b>Bascules prévues</b>{d.transfers.map((t) => <div key={t.time + t.title} className="text-xs">{t.time} · {t.title} — {t.description}</div>)}</div>}
    </Section>);
}
