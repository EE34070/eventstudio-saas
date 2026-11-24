import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { download } from "@/core/api/client";
import { useWpMutation, wp, type Food, type Wedding } from "../api";
import { Loading, Section, toast } from "../ui";

const UNITS = { bottle: "bouteilles", keg: "fûts", l: "litres" } as const;
const EMPTY: Food = { vendor: "", formula: "", price: "", notes: "", courses: [{ name: "Plat", chosen: "", options: [] }], included: [], external: [] };

export function FoodAdmin({ w }: { w: Wedding }) {
  const events = w.events.filter((e) => e.enabled);
  const [key, setKey] = useState(events.find((e) => e.key === "dj")?.key ?? events[0]?.key);
  const { data, isLoading } = useQuery({ queryKey: ["wp", "food", w.id, key], queryFn: () => wp.food(w.id, key!), enabled: !!key });
  const [f, setF] = useState<Food | null>(null);
  useEffect(() => setF(data?.food ?? null), [data]);
  const save = useWpMutation((x: Food) => wp.saveFood(w.id, key!, x), () => toast("Repas et boissons enregistrés"));
  const g = data?.guests ?? null;
  const sectionOpen = w.open_sections.includes("food");

  const upd = (patch: Partial<Food>) => setF((x) => (x ? { ...x, ...patch } : x));
  return (
    <div>
      <div className="note">Vous modifiez ici ce que les mariés voient dans « Repas et boissons ». Les notes internes ne sont jamais visibles par le couple.
        {!sectionOpen && " Cette rubrique n'est pas encore ouverte dans l'espace du couple (Compte et droits)."}</div>
      <div className="row" style={{ margin: "14px 0" }}>
        {events.map((e) => <button key={e.key} className={`btn${key === e.key ? "" : " ghost"}`} onClick={() => setKey(e.key)}>{e.name}</button>)}
      </div>
      {isLoading || !data ? <Loading /> : (
        <>
          <div className="kicker">{data.event.name} · {g ?? "?"} invités ({data.guests_source === "guest_list" ? "Guest List" : "estimation"})</div>
          <Section kicker="Prestataire rattaché à cet événement">
            {f ? (
              <div className="two">
                <div><label className="l">Prestataire</label><input value={f.vendor} onChange={(e) => upd({ vendor: e.target.value })} /></div>
                <div className="row" style={{ alignItems: "end" }}>
                  <button className="btn ghost small" onClick={() => save.mutate({ ...f, vendor: "" })}>Détacher ce traiteur</button>
                </div>
              </div>
            ) : (
              <div className="row" style={{ marginTop: 8 }}>
                <span>Aucun prestataire validé. Les mariés voient « Choisissez d'abord votre traiteur ».</span>
                <button className="btn" onClick={() => setF({ ...EMPTY })}>Rattacher un traiteur</button>
              </div>
            )}
            <div className="note" style={{ marginTop: 12 }}>Les prestataires proposés viendront de votre catalogue (phase 3). En attendant, saisissez le nom du traiteur validé.</div>
          </Section>
          {f && (
            <>
              <Section>
                <div className="two">
                  <div><label className="l">Formule</label><input value={f.formula} onChange={(e) => upd({ formula: e.target.value })} /></div>
                  <div><label className="l">Prix</label><input value={f.price ?? ""} onChange={(e) => upd({ price: e.target.value })} /></div>
                </div>
              </Section>
              <Section title="Menu">
                {f.courses.map((c, i) => (
                  <div key={i} className="qa">
                    <div className="two">
                      <div><label className="l">Service</label><input value={c.name} onChange={(e) => upd({ courses: f.courses.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} /></div>
                      <div><label className="l">Choix retenu</label><input value={c.chosen} onChange={(e) => upd({ courses: f.courses.map((x, j) => j === i ? { ...x, chosen: e.target.value } : x) })} /></div>
                    </div>
                    <label className="l">Options proposées</label>
                    <input value={c.options.join(", ")} placeholder="Options séparées par une virgule"
                           onChange={(e) => upd({ courses: f.courses.map((x, j) => j === i ? { ...x, options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } : x) })} />
                    <button className="btn ghost small" style={{ marginTop: 8 }} onClick={() => upd({ courses: f.courses.filter((_, j) => j !== i) })}>Retirer ce service</button>
                  </div>
                ))}
                <button className="btn ghost" onClick={() => upd({ courses: [...f.courses, { name: "Nouveau service", chosen: "", options: [] }] })}>Ajouter un service</button>
              </Section>
              <Section title="Boissons incluses">
                {f.included.map((d, i) => (
                  <div key={i} className="two qa">
                    <input value={d.name} aria-label="Boisson incluse" onChange={(e) => upd({ included: f.included.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} />
                    <div className="row">
                      <input value={d.detail} style={{ flex: 1 }} aria-label="Détail" onChange={(e) => upd({ included: f.included.map((x, j) => j === i ? { ...x, detail: e.target.value } : x) })} />
                      <button className="btn ghost small" onClick={() => upd({ included: f.included.filter((_, j) => j !== i) })}>Retirer</button>
                    </div>
                  </div>
                ))}
                <button className="btn ghost" onClick={() => upd({ included: [...f.included, { name: "Nouvelle boisson", detail: "" }] })}>Ajouter une boisson incluse</button>
              </Section>
              <Section title="Boissons d'un autre fournisseur">
                <div className="tablewrap"><table>
                  <thead><tr><th>Boisson</th><th>Fournisseur</th><th>Par invité</th><th>Unité</th><th>Quantité à commander</th><th /></tr></thead>
                  <tbody>{f.external.map((d, i) => {
                    const set = (p: Partial<typeof d>) => upd({ external: f.external.map((x, j) => j === i ? { ...x, ...p } : x) });
                    return (
                      <tr key={i}>
                        <td><input value={d.name} aria-label="Boisson" onChange={(e) => set({ name: e.target.value })} /></td>
                        <td><input value={d.supplier} aria-label="Fournisseur" onChange={(e) => set({ supplier: e.target.value })} /></td>
                        <td><input type="number" step="0.1" min="0" value={d.per_guest} style={{ width: 80 }} aria-label="Par invité"
                                   onChange={(e) => set({ per_guest: parseFloat(e.target.value) || 0 })} /></td>
                        <td><select value={d.unit} aria-label="Unité" onChange={(e) => set({ unit: e.target.value as typeof d.unit })}>
                          {Object.entries(UNITS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
                        <td className="num">{g == null ? "?" : `${Math.ceil(g * d.per_guest)} ${UNITS[d.unit]}`}</td>
                        <td><button className="btn ghost small" onClick={() => upd({ external: f.external.filter((_, j) => j !== i) })}>Retirer</button></td>
                      </tr>
                    );
                  })}</tbody>
                </table></div>
                <button className="btn ghost" style={{ marginTop: 10 }} onClick={() => upd({ external: [...f.external, { name: "Nouvelle boisson", supplier: "", per_guest: 0.3, unit: "bottle" }] })}>Ajouter une boisson</button>
              </Section>
            </>
          )}
          <Section title="Contraintes alimentaires de cet événement" kicker="Calculées depuis la Guest List">
            {data.diets.length ? data.diets.map((d, i) => (
              <div key={i} className="qa"><div className="row"><span className={`pill${d.allergy ? " warn" : ""}`}>{d.allergy ? `Allergie : ${d.label}` : d.label}</span><span>{d.names}</span></div></div>
            )) : <p className="muted">Elles s'afficheront ici dès que la Guest List sera ouverte (régimes et allergies saisis par invité).</p>}
            {f && data.food && <button className="btn ghost" style={{ marginTop: 10 }} onClick={() => download(`/wedding-planner/weddings/${w.id}/food/${key}/pdf`, `traiteur-${key}.pdf`).then(() => toast("Fiche traiteur téléchargée"))}>Exporter pour le traiteur (PDF)</button>}
          </Section>
          {f && (
            <Section title="Notes internes">
              <span className="pill warn">Invisible pour les mariés</span>
              <textarea style={{ marginTop: 10 }} value={f.notes ?? ""} aria-label="Notes internes" onChange={(e) => upd({ notes: e.target.value })} />
            </Section>
          )}
          {f && <div className="row" style={{ marginTop: 18 }}><button className="btn" disabled={save.isPending || !f.vendor} onClick={() => save.mutate(f, { onError: (e) => toast(e.message) })}>Enregistrer</button></div>}
        </>
      )}
    </div>
  );
}
